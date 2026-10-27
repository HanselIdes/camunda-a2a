#!/usr/bin/env python3
"""Use the pinned bpmn-io auto-layout engine on every experiment-3 BPMN diagram."""
import argparse
from copy import deepcopy
from math import hypot
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NODE_SCRIPT = ROOT / "tools/layout_process.mjs"
BPMN_DI = "{http://www.omg.org/spec/BPMN/20100524/DI}BPMNDiagram"
DI = "{http://www.omg.org/spec/BPMN/20100524/DI}"
BPMN_PLANE = DI + "BPMNPlane"
BPMN_SHAPE = DI + "BPMNShape"
BPMN_EDGE = DI + "BPMNEdge"
BPMN_LABEL = DI + "BPMNLabel"
BPMN_PROCESS = "{http://www.omg.org/spec/BPMN/20100524/MODEL}process"
BPMN_COLLABORATION = "{http://www.omg.org/spec/BPMN/20100524/MODEL}collaboration"
DC_BOUNDS = "{http://www.omg.org/spec/DD/20100524/DC}Bounds"
DI_WAYPOINT = "{http://www.omg.org/spec/DD/20100524/DI}waypoint"

for prefix, uri in {
    "bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL",
    "bpmndi": DI[1:-1],
    "dc": "http://www.omg.org/spec/DD/20100524/DC",
    "di": "http://www.omg.org/spec/DD/20100524/DI",
    "modeler": "http://camunda.org/schema/modeler/1.0",
    "zeebe": "http://camunda.org/schema/zeebe/1.0",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
}.items():
    ET.register_namespace(prefix, uri)


def semantics(element):
    if not isinstance(element.tag, str):
        return None
    if element.tag.startswith(DI):
        return None
    children = [value for child in element for value in [semantics(child)] if value is not None]
    text = element.text if element.text and element.text.strip() else None
    return element.tag, tuple(sorted(element.attrib.items())), text, tuple(children)


def _layout_process(source_root, process):
    layout_input = deepcopy(source_root)
    target = next(element for element in layout_input if element.get("id") == process.get("id"))
    target_ids = {element.get("id") for element in target.iter() if element.get("id")}
    source_diagrams = list(layout_input.iter(BPMN_DI))
    for element in list(layout_input):
        if element.tag in (BPMN_COLLABORATION, BPMN_DI):
            layout_input.remove(element)
        elif element.tag == BPMN_PROCESS and element is not target:
            layout_input.remove(element)

    diagram = ET.SubElement(layout_input, BPMN_DI, id=f"Layout_Diagram_{process.get('id')}")
    plane = ET.SubElement(
        diagram,
        BPMN_PLANE,
        id=f"Layout_Plane_{process.get('id')}",
        bpmnElement=process.get("id"),
    )
    for source_diagram in source_diagrams:
        source_plane = source_diagram.find(BPMN_PLANE)
        if source_plane is None:
            continue
        for element in source_plane:
            if element.tag in (BPMN_SHAPE, BPMN_EDGE) and element.get("bpmnElement") in target_ids:
                plane.append(deepcopy(element))

    xml = ET.tostring(layout_input, encoding="UTF-8", xml_declaration=True)
    result = subprocess.run(
        ["node", str(NODE_SCRIPT)],
        input=xml,
        capture_output=True,
        check=True,
        cwd=ROOT / "tools",
    )
    generated = ET.fromstring(result.stdout)
    diagram = next((element for element in generated.iter(BPMN_DI)
                    if (plane := element.find(BPMN_PLANE)) is not None
                    and plane.get("bpmnElement") == process.get("id")), None)
    if diagram is None:
        raise ValueError(f"bpmn-auto-layout did not create a diagram for {process.get('id')}")
    return diagram, result.stderr


def _move_di(element, dx, dy):
    for part in element.iter():
        if part.tag == DC_BOUNDS:
            part.set("x", str(float(part.get("x")) + dx))
            part.set("y", str(float(part.get("y")) + dy))
        elif part.tag == DI_WAYPOINT:
            part.set("x", str(float(part.get("x")) + dx))
            part.set("y", str(float(part.get("y")) + dy))


def _edge_midpoint(edge):
    points = [(float(point.get("x")), float(point.get("y")))
              for point in edge.findall(DI_WAYPOINT)]
    if not points:
        return None
    lengths = [hypot(end[0] - start[0], end[1] - start[1])
               for start, end in zip(points, points[1:])]
    half_length = sum(lengths) / 2
    traversed = 0
    for (start, end), length in zip(zip(points, points[1:]), lengths):
        if traversed + length >= half_length:
            fraction = (half_length - traversed) / length if length else 0
            return (start[0] + (end[0] - start[0]) * fraction,
                    start[1] + (end[1] - start[1]) * fraction)
        traversed += length
    return points[-1]


def _reposition_label(existing, replacement):
    label = existing.find(BPMN_LABEL)
    if label is None or replacement.find(BPMN_LABEL) is not None:
        return
    label = deepcopy(label)
    label_bounds = label.find(DC_BOUNDS)
    if label_bounds is None:
        replacement.append(label)
        return

    if existing.tag == BPMN_SHAPE:
        old_bounds = existing.find(DC_BOUNDS)
        new_bounds = replacement.find(DC_BOUNDS)
        if old_bounds is None or new_bounds is None:
            replacement.append(label)
            return
        old_anchor = (
            float(old_bounds.get("x")) + float(old_bounds.get("width")) / 2,
            float(old_bounds.get("y")) + float(old_bounds.get("height")) / 2,
        )
        new_anchor = (
            float(new_bounds.get("x")) + float(new_bounds.get("width")) / 2,
            float(new_bounds.get("y")) + float(new_bounds.get("height")) / 2,
        )
    else:
        old_anchor = _edge_midpoint(existing)
        new_anchor = _edge_midpoint(replacement)
        if old_anchor is None or new_anchor is None:
            replacement.append(label)
            return

    label_center = (
        float(label_bounds.get("x")) + float(label_bounds.get("width")) / 2,
        float(label_bounds.get("y")) + float(label_bounds.get("height")) / 2,
    )
    if hypot(label_center[0] - old_anchor[0], label_center[1] - old_anchor[1]) > 80:
        return
    dx, dy = new_anchor[0] - old_anchor[0], new_anchor[1] - old_anchor[1]
    label_bounds.set("x", str(float(label_bounds.get("x")) + dx))
    label_bounds.set("y", str(float(label_bounds.get("y")) + dy))
    replacement.append(label)


def _merge_plane(target_plane, generated_plane, dx=0, dy=0):
    generated = []
    for element in generated_plane:
        moved = deepcopy(element)
        _move_di(moved, dx, dy)
        generated.append(moved)

    lookup = {(element.tag, element.get("bpmnElement")): element for element in generated
              if element.tag in (BPMN_SHAPE, BPMN_EDGE)}
    original = list(target_plane)
    for existing in original:
        if existing.tag in (BPMN_SHAPE, BPMN_EDGE):
            replacement = lookup.get((existing.tag, existing.get("bpmnElement")))
            if replacement is None:
                continue
            if existing.tag == BPMN_SHAPE and existing.get("isExpanded") == "true":
                replacement.set("isExpanded", "true")
            _reposition_label(existing, replacement)
            position = list(target_plane).index(existing)
            target_plane.remove(existing)
            target_plane.insert(position, replacement)
            generated.remove(replacement)
        elif existing.get("id") and not any(child.get("id") == existing.get("id")
                                            for child in generated):
            continue

    for element in generated:
        target_plane.append(element)


def _shape_bounds(plane, element_id):
    shape = next((element for element in plane.findall(BPMN_SHAPE)
                  if element.get("bpmnElement") == element_id), None)
    return shape.find(DC_BOUNDS) if shape is not None else None


def _route_server_follow_up(plane):
    edge = next((element for element in plane.findall(BPMN_EDGE)
                 if element.get("bpmnElement") == "Flow_FollowUp_NextTurn"), None)
    follow_up = _shape_bounds(plane, "FollowUp")
    next_turn = _shape_bounds(plane, "NextTurn")
    host = _shape_bounds(plane, "AgentTools")
    if edge is None or follow_up is None or next_turn is None or host is None:
        return

    source_x = float(follow_up.get("x")) + float(follow_up.get("width"))
    source_y = float(follow_up.get("y")) + float(follow_up.get("height")) / 2
    target_x = float(next_turn.get("x")) + float(next_turn.get("width")) / 2
    target_y = float(next_turn.get("y"))
    route_y = max(0, float(host.get("y")) - 20)
    for waypoint in edge.findall(DI_WAYPOINT):
        edge.remove(waypoint)
    for x, y in ((source_x, source_y), (source_x, route_y),
                 (target_x, route_y), (target_x, target_y)):
        ET.SubElement(edge, DI_WAYPOINT, {"x": str(x), "y": str(y)})


def _set_edge_route(plane, edge_id, points):
    edge = next((element for element in plane.findall(BPMN_EDGE)
                 if element.get("bpmnElement") == edge_id), None)
    if edge is None:
        return
    for waypoint in edge.findall(DI_WAYPOINT):
        edge.remove(waypoint)
    for x, y in points:
        ET.SubElement(edge, DI_WAYPOINT, {"x": str(x), "y": str(y)})


def _set_edge_label(plane, edge_id, x, y, width):
    edge = next((element for element in plane.findall(BPMN_EDGE)
                 if element.get("bpmnElement") == edge_id), None)
    if edge is None:
        return
    label = edge.find(BPMN_LABEL)
    if label is None:
        label = ET.Element(BPMN_LABEL)
    else:
        for child in list(label):
            label.remove(child)
        edge.remove(label)
    edge.append(label)
    ET.SubElement(label, DC_BOUNDS, {
        "x": str(x), "y": str(y), "width": str(width), "height": "14",
    })


def _route_list_scan_decision(plane):
    decision = _shape_bounds(plane, "ListScanDecision")
    wait = _shape_bounds(plane, "WaitListVariables")
    fail = _shape_bounds(plane, "FailListScan")
    page_join = _shape_bounds(plane, "ListProcessPageJoin")
    if any(bounds is None for bounds in (decision, wait, fail, page_join)):
        return

    source_center_x = float(decision.get("x")) + float(decision.get("width")) / 2
    source_bottom_y = float(decision.get("y")) + float(decision.get("height"))
    source_right_x = float(decision.get("x")) + float(decision.get("width"))
    source_center_y = float(decision.get("y")) + float(decision.get("height")) / 2
    wait_bottom = float(wait.get("y")) + float(wait.get("height"))
    wait_route_x = min(float(page_join.get("x")), float(wait.get("x"))) - 20
    wait_route_y = wait_bottom + 24
    wait_x = float(wait.get("x")) + float(wait.get("width")) / 2
    wait_y = wait_bottom
    _set_edge_route(plane, "Flow_ListScanDecision_WaitListVariables", (
        (source_center_x, source_bottom_y),
        (source_center_x, wait_route_y),
        (wait_route_x, wait_route_y),
        (wait_route_x, wait_y),
        (wait_x, wait_y),
    ))
    _set_edge_label(plane, "Flow_ListScanDecision_WaitListVariables",
                    (source_center_x + wait_route_x) / 2 - 45, wait_route_y - 20, 90)

    fail_x = float(fail.get("x"))
    fail_y = float(fail.get("y"))
    fail_route_x = fail_x + float(fail.get("width")) + 72
    fail_route_y = fail_y - 28
    _set_edge_route(plane, "Flow_ListScanDecision_FailListScan", (
        (source_right_x, source_center_y),
        (source_right_x, fail_route_y),
        (fail_route_x, fail_route_y),
        (fail_route_x, fail_y),
        (fail_x + float(fail.get("width")) / 2, fail_y),
    ))
    _set_edge_label(plane, "Flow_ListScanDecision_FailListScan",
                    (source_right_x + fail_route_x) / 2 - 40, fail_route_y - 20, 80)


def _place_client_gateway_label(plane):
    shape = next((element for element in plane.findall(BPMN_SHAPE)
                  if element.get("bpmnElement") == "ClientHasTools"), None)
    bounds = shape.find(DC_BOUNDS) if shape is not None else None
    if bounds is None:
        return
    label = shape.find(BPMN_LABEL)
    if label is None:
        label = ET.SubElement(shape, BPMN_LABEL)
    else:
        for child in list(label):
            label.remove(child)
    ET.SubElement(label, DC_BOUNDS, {
        "x": str(float(bounds.get("x")) + float(bounds.get("width")) / 2 - 70),
        "y": str(float(bounds.get("y")) - 35),
        "width": "140",
        "height": "30",
    })


def _place_gateway_labels(plane, process):
    shapes = {shape.get("bpmnElement"): shape for shape in plane.findall(BPMN_SHAPE)}
    for gateway in process.iter():
        if not gateway.tag.endswith("Gateway") or not gateway.get("name"):
            continue
        shape = shapes.get(gateway.get("id"))
        bounds = shape.find(DC_BOUNDS) if shape is not None else None
        if bounds is None:
            continue
        label = shape.find(BPMN_LABEL)
        label_bounds = label.find(DC_BOUNDS) if label is not None else None
        width = float(label_bounds.get("width")) if label_bounds is not None else min(
            180, max(50, len(gateway.get("name")) * 7))
        height = float(label_bounds.get("height")) if label_bounds is not None else (
            28 if len(gateway.get("name")) * 7 > width else 14
        )
        x = float(bounds.get("x")) + float(bounds.get("width")) / 2 - width / 2
        y = float(bounds.get("y")) - height - 8
        if label is None:
            label = ET.SubElement(shape, BPMN_LABEL)
        else:
            for child in list(label):
                label.remove(child)
        ET.SubElement(label, DC_BOUNDS, {
            "x": str(x),
            "y": str(y),
            "width": f"{width:g}",
            "height": f"{height:g}",
        })


def _apply_process_layout_fixes(plane, process_id, process):
    if process is not None and process_id.startswith("a2a-"):
        _place_gateway_labels(plane, process)
    if process_id == "a2a-card-dispute":
        _route_server_follow_up(plane)
    elif process_id == "a2a-list-collect":
        _route_list_scan_decision(plane)
    elif process_id == "a2a-client":
        _place_client_gateway_label(plane)
        _set_edge_label(
            plane, "Flow_ClientHasTools_PrepareClientResult", 425, 420, 90)


def _compact_collaboration(plane, collaboration, processes, participants):
    shapes = {shape.get("bpmnElement"): shape for shape in plane.findall(BPMN_SHAPE)}
    layouts = []
    for participant in collaboration:
        process_ref = participant.get("processRef")
        process = processes.get(process_ref)
        participant_shape = shapes.get(participant.get("id"))
        bounds = participant_shape.find(DC_BOUNDS) if participant_shape is not None else None
        if process is None or bounds is None:
            continue

        members = {element.get("id") for element in process.iter() if element.get("id")}
        extents = []
        for element in plane:
            if element.get("bpmnElement") not in members:
                continue
            if element.tag == BPMN_SHAPE:
                box = element.find(DC_BOUNDS)
                if box is not None:
                    extents.append((
                        float(box.get("x")),
                        float(box.get("y")),
                        float(box.get("x")) + float(box.get("width")),
                        float(box.get("y")) + float(box.get("height")),
                    ))
            elif element.tag == BPMN_EDGE:
                points = element.findall(DI_WAYPOINT)
                if points:
                    xs = [float(point.get("x")) for point in points]
                    ys = [float(point.get("y")) for point in points]
                    extents.append((min(xs), min(ys), max(xs), max(ys)))
        if not extents:
            continue

        x = float(bounds.get("x"))
        y = float(bounds.get("y"))
        right = max(item[2] for item in extents)
        bottom = max(item[3] for item in extents)
        bounds.set("width", str(max(100, right + 50 - x)))
        bounds.set("height", str(max(100, bottom + 30 - y)))
        layouts.append((y, process_ref, participant.get("id"), members, bounds))

    next_y = min((item[0] for item in layouts), default=0)
    for _, process_ref, participant_id, members, bounds in sorted(layouts):
        old_y = float(bounds.get("y"))
        delta_y = next_y - old_y
        if delta_y:
            _move_di(shapes[participant_id], 0, delta_y)
            for element in plane:
                if element.get("bpmnElement") in members:
                    _move_di(element, 0, delta_y)
        next_y += float(bounds.get("height")) + 60


def layout_xml(source):
    original = ET.fromstring(source, ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)))
    original_semantics = semantics(original)
    original_ids = {element.get("id") for element in original.iter() if element.get("id")}
    warnings = []
    diagrams = list(original.iter(BPMN_DI))
    collaborations = {element.get("id"): element for element in original.iter(BPMN_COLLABORATION)}
    process_participants = {}
    for collaboration in collaborations.values():
        for participant in collaboration:
            process_ref = participant.get("processRef")
            if process_ref:
                process_participants[process_ref] = participant.get("id")

    process_planes = {}
    processes = {process.get("id"): process for process in original.findall(BPMN_PROCESS)}
    for process in processes.values():
        generated_diagram, warning = _layout_process(original, process)
        if warning:
            warnings.append(warning.decode("utf-8"))
        generated_plane = generated_diagram.find(BPMN_PLANE)
        for element in generated_plane:
            if element.tag in (BPMN_SHAPE, BPMN_EDGE):
                reference = element.get("bpmnElement")
                if reference and reference not in original_ids:
                    raise ValueError(f"generated diagram refers to missing BPMN element {reference}")
        process_planes[process.get("id")] = generated_plane

    for diagram in diagrams:
        plane = diagram.find(BPMN_PLANE)
        if plane is None:
            continue
        reference = plane.get("bpmnElement")
        if reference in process_planes:
            generated_plane = process_planes.pop(reference)
            _merge_plane(plane, generated_plane)
            _apply_process_layout_fixes(plane, reference, processes.get(reference))
            continue
        collaboration = collaborations.get(reference)
        if collaboration is None:
            continue
        participant_shapes = {
            shape.get("bpmnElement"): shape
            for shape in plane.findall(BPMN_SHAPE)
        }
        for process in collaboration:
            process_ref = process.get("processRef")
            generated_plane = process_planes.pop(process_ref, None)
            participant_id = process_participants.get(process_ref)
            participant_shape = participant_shapes.get(participant_id)
            bounds = participant_shape.find(DC_BOUNDS) if participant_shape is not None else None
            if generated_plane is None or bounds is None:
                continue
            extents = [shape.find(DC_BOUNDS) for shape in generated_plane.findall(BPMN_SHAPE)]
            extents = [item for item in extents if item is not None]
            min_x = min(float(item.get("x")) for item in extents)
            min_y = min(float(item.get("y")) for item in extents)
            dx = float(bounds.get("x")) + 100 - min_x
            dy = float(bounds.get("y")) + 30 - min_y
            _merge_plane(plane, generated_plane, dx, dy)
        if not any(element.tag.endswith("}messageFlow") for element in collaboration):
            _compact_collaboration(plane, collaboration, processes, process_participants)
        for process in collaboration:
            process_ref = process.get("processRef")
            _apply_process_layout_fixes(plane, process_ref, processes.get(process_ref))

    if process_planes:
        raise ValueError("No Diagram Interchange plane found for process(es): "
                         + ", ".join(sorted(process_planes)))

    if semantics(original) != original_semantics:
        raise ValueError("Diagram interchange merge changed BPMN content outside Diagram Interchange")
    if warnings:
        print("\n".join(warnings), file=sys.stderr)
    ET.indent(original, space="  ")
    return ET.tostring(original, encoding="UTF-8", xml_declaration=True) + b"\n"


def diagram_paths():
    roots = (
        ROOT / "bpmn",
        ROOT / "blueprint",
        ROOT / "tck" / "fixture",
        ROOT / "tests" / "src" / "test" / "resources",
    )
    return sorted(path for base in roots if base.exists() for path in base.rglob("*.bpmn"))


def layout_all(check=False):
    paths = diagram_paths()
    stale = []
    for path in paths:
        source = path.read_bytes()
        try:
            laid_out = layout_xml(source)
        except subprocess.CalledProcessError as error:
            detail = error.stderr.decode("utf-8", errors="replace") if error.stderr else str(error)
            raise ValueError(f"{path.relative_to(ROOT)}: {detail}") from error
        except ValueError as error:
            raise ValueError(f"{path.relative_to(ROOT)}: {error}") from error
        if check:
            if source != laid_out:
                stale.append(path.relative_to(ROOT).as_posix())
        else:
            path.write_bytes(laid_out)
    if stale:
        raise ValueError("Stale auto-layout: " + ", ".join(stale))
    return len(paths)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if any BPMN file is not layout-engine output")
    args = parser.parse_args()
    try:
        count = layout_all(check=args.check)
    except ValueError as error:
        parser.exit(1, f"{error}\n")
    print(("All " if args.check else "Laid out ") + f"{count} experiment-3 BPMN diagrams")


if __name__ == "__main__":
    main()
