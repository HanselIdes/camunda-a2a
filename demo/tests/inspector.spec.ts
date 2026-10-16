import { expect, Page, test } from '@playwright/test';

const AGENT_URL = process.env.AGENT_URL ?? 'http://localhost:18090';

// Prompts and expectations come from the CPT tests (AgentTest, OllamaAgentTest) and the smoke test.
// Model wording varies, so the assertions are about tools used and key facts, never exact text.

async function connect(page: Page) {
  await page.goto('/');
  await page.locator('#agent-card-url').fill(AGENT_URL);
  await page.locator('#connect-btn').click();
  await expect(page.locator('#agent-card-content')).toContainText('camunda-a2a');
  await expect(page.locator('#chat-input')).toBeEnabled();
}

/**
 * Sends a message and returns the text of the agent bubbles that arrived for it. The inspector shows each task
 * artifact as one bubble: the agent's answer (or question) and the tool trace.
 */
async function ask(page: Page, text: string): Promise<string> {
  const agentMessages = page.locator('#chat-messages .message.agent');
  const errors = page.locator('#chat-messages .message.error');
  const before = await agentMessages.count();
  for (let attempt = 1; attempt <= 3; attempt++) {
    const errorsBefore = await errors.count();
    await page.locator('#chat-input').fill(text);
    await page.locator('#send-btn').click();
    // Either the agent answers, or the inspector reports that its backend session was lost (a socket
    // reconnect on a busy machine). In that case connect again and resend, which is what a user would do.
    await expect.poll(async () => (await agentMessages.count()) !== before || (await errors.count()) > errorsBefore)
      .toBe(true);
    if ((await agentMessages.count()) !== before) break;
    await page.locator('#connect-btn').click();
    await expect(page.locator('#chat-input')).toBeEnabled();
  }
  await expect(page.locator('#chat-messages .agent-loading')).toHaveCount(0);
  const all = await agentMessages.allInnerTexts();
  return all.slice(before).join('\n').trim();
}

async function rawConsole(page: Page): Promise<string> {
  if (await page.locator('#debug-console.hidden').count()) {
    await page.locator('#toggle-console-btn').click();
  }
  return page.locator('#debug-content').innerText();
}

test.describe.serial('camunda-a2a through the a2a-inspector', () => {
  test('shows the Agent Card with the three tools as skills and passes the inspector checks', async ({ page }) => {
    await connect(page);
    const card = page.locator('#agent-card-content');
    for (const skill of ['get_current_time', 'convert_temperature', 'capital_of']) {
      await expect(card).toContainText(skill);
    }
    await expect(card).toContainText('http://localhost:18090/a2a');
    await expect(page.locator('#session-transport')).toContainText(/JSONRPC/i);
    await expect(page.locator('#validation-errors')).not.toContainText(/error/i);
    await page.screenshot({ path: 'artifacts/01-agent-card.png' });
  });

  test('answers "What time is it?" using the time tool', async ({ page }) => {
    await connect(page);
    const reply = await ask(page, 'What time is it?');
    expect(reply).toMatch(/\d{1,2}:\d{2}|UTC/i);
    expect(reply).toContain('get_current_time');
    const raw = await rawConsole(page);
    expect(raw).toMatch(/"state": "completed"/i);
    expect(raw).toContain('get_current_time');
    await page.screenshot({ path: 'artifacts/02-time.png' });
  });

  test('looks up a capital city with the decision table tool', async ({ page }) => {
    await connect(page);
    const reply = await ask(page, 'What is the capital of Japan?');
    expect(reply).toContain('Tokyo');
    expect(await rawConsole(page)).toContain('capital_of');
    await page.screenshot({ path: 'artifacts/03-capital.png' });
  });

  test('converts a temperature with the scripted tool', async ({ page }) => {
    await connect(page);
    const reply = await ask(page, 'Convert 100 celsius to fahrenheit');
    expect(reply).toContain('212');
    expect(await rawConsole(page)).toContain('convert_temperature');
    await page.screenshot({ path: 'artifacts/04-temperature.png' });
  });

  test('asks for missing input and then answers the follow-up in the same context', async ({ page }) => {
    await connect(page);
    let question = '';
    for (let attempt = 1; attempt <= 3; attempt++) {
      question = await ask(page, 'Please convert a temperature for me.');
      if (/input[-_ ]required/i.test(await rawConsole(page))) break;
    }
    expect(await rawConsole(page)).toMatch(/input[-_ ]required/i);
    expect(question.length).toBeGreaterThan(0);
    await page.screenshot({ path: 'artifacts/05-input-required.png' });
    const answer = await ask(page, '100 celsius to fahrenheit');
    expect(answer).toContain('212');
    await page.screenshot({ path: 'artifacts/06-follow-up.png' });
  });

  test('shows the request and the task response in the debug console', async ({ page }) => {
    await connect(page);
    await ask(page, 'What is the capital of France?');
    const raw = await rawConsole(page);
    expect(raw).toContain('"transport": "JSONRPC"');
    expect(raw).toContain('"method": "SendMessage"');
    expect(raw).toContain('What is the capital of France?');
    expect(raw).toMatch(/"state": "completed"/i);
    await page.screenshot({ path: 'artifacts/07-debug-console.png' });
  });
});
