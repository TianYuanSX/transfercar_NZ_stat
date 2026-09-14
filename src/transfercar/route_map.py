"""Directed, quantity-encoded routes from reviewed geographic reference points."""

import json
import math
from collections import defaultdict
from importlib.resources import files

import pydeck as pdk


def location_catalog():
    return json.loads(files("transfercar").joinpath("data/nz_locations.json").read_text())[
        "locations"
    ]


def aggregate_snapshot(rows):
    routes = defaultdict(lambda: {"quantity": 0, "listing_count": 0})
    for row in rows:
        key = (row["pickup_location"], row["dropoff_location"])
        routes[key]["quantity"] += row["nb_listings"]
        routes[key]["listing_count"] += 1
    return [
        {"pickup": pickup, "dropoff": dropoff, **values}
        for (pickup, dropoff), values in sorted(routes.items())
    ]


def filter_routes(routes, pickups=(), dropoffs=()):
    return [
        r
        for r in routes
        if (not pickups or r["pickup"] in pickups) and (not dropoffs or r["dropoff"] in dropoffs)
    ]


def direction_style(start, end):
    """Compare latitude, including negative latitudes in the Southern Hemisphere."""
    if math.isclose(start[1], end[1], rel_tol=0, abs_tol=1e-6):
        return "Same latitude / local", [125, 135, 145, 150]
    if end[1] < start[1]:
        return "North → South", [32, 124, 190, 150]
    return "South → North", [21, 157, 103, 150]


def curved_path(start, end, lane, lane_count, steps=28):
    """A directed Bezier fan. Reversed routes bend to the opposite side.

    Work in a local equirectangular plane so arrowheads retain their direction.
    Same-coordinate routes use a loop instead of a zero-length line.
    """
    scale = math.cos(math.radians((start[1] + end[1]) / 2))
    a = (start[0] * scale, start[1])
    b = (end[0] * scale, end[1])
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    if length < 1e-8:
        radius = 0.035 + 0.12 * (lane + 1) / max(1, lane_count)
        return [
            [
                (a[0] + radius * math.sin(2 * math.pi * t / steps)) / scale,
                a[1] + radius * (1 - math.cos(2 * math.pi * t / steps)),
            ]
            for t in range(steps + 1)
        ]
    fan = (lane / max(1, lane_count - 1) - 0.5) if lane_count > 1 else 0
    bend = length * 0.22 + fan * min(0.8, length * 0.35)
    control = ((a[0] + b[0]) / 2 - dy / length * bend, (a[1] + b[1]) / 2 + dx / length * bend)
    path = []
    for step in range(steps + 1):
        t = step / steps
        x = (1 - t) ** 2 * a[0] + 2 * (1 - t) * t * control[0] + t**2 * b[0]
        y = (1 - t) ** 2 * a[1] + 2 * (1 - t) * t * control[1] + t**2 * b[1]
        path.append([x / scale, y])
    return path


def arrowhead(path):
    index = int((len(path) - 1) * 0.72)
    tip, behind = path[index], path[index - 1]
    scale = math.cos(math.radians(tip[1]))
    dx, dy = (tip[0] - behind[0]) * scale, tip[1] - behind[1]
    distance = math.hypot(dx, dy)
    ux, uy = dx / distance, dy / distance
    size = min(0.09, max(0.008, distance * 0.8))
    bx, by = tip[0] * scale - ux * size, tip[1] - uy * size
    width = size * 0.45
    return [
        tip,
        [(bx - uy * width) / scale, by + ux * width],
        [(bx + uy * width) / scale, by - ux * width],
        tip,
    ]


def geometry(routes, units_per_line=1, catalog=None, max_lines=5000):
    if units_per_line <= 0 or not math.isfinite(units_per_line):
        raise ValueError("units_per_line must be positive")
    if max_lines < 1:
        raise ValueError("max_lines must be positive")
    catalog = location_catalog() if catalog is None else catalog
    known, missing = [], []
    for route in routes:
        quantity = float(route["quantity"])
        if quantity < 0 or not math.isfinite(quantity):
            raise ValueError("route quantity must be finite and nonnegative")
        if route["pickup"] not in catalog or route["dropoff"] not in catalog:
            missing.append(route)
        else:
            known.append(route)
    # Never silently truncate flows: increase the common scale and report it in the legend.
    scale = float(units_per_line)
    while sum(math.ceil(float(r["quantity"]) / scale) for r in known) > max_lines:
        scale *= 2
    lines, arrows, nodes = [], [], {}
    for route in known:
        quantity = float(route["quantity"])
        if quantity < 0 or not math.isfinite(quantity):
            raise ValueError("route quantity must be finite and nonnegative")
        count = math.ceil(quantity / scale)
        for role, key in (("pickup", "outbound"), ("dropoff", "inbound")):
            name = route[role]
            point = catalog[name]
            node = nodes.setdefault(
                name,
                {
                    "name": name,
                    "position": [point["longitude"], point["latitude"]],
                    "outbound": 0.0,
                    "inbound": 0.0,
                    "precision": point["precision"],
                },
            )
            node[key] += quantity
        start = nodes[route["pickup"]]["position"]
        end = nodes[route["dropoff"]]["position"]
        direction, color = direction_style(start, end)
        tooltip = (
            f"{route['pickup']} → {route['dropoff']}\n"
            f"Direction: {direction}\n"
            f"Source quantity: {quantity:g}\n"
            f"Listing count: {float(route['listing_count']):g}\n"
            f"{count} lines; up to {scale:g} source units per line"
        )
        for lane in range(count):
            path = curved_path(start, end, lane, count)
            represented = min(scale, quantity - lane * scale)
            line_color = [*color[:3], max(50, round(color[3] * represented / scale))]
            lines.append(
                {
                    "path": path,
                    "color": line_color,
                    "tooltip": tooltip,
                    "represented_quantity": represented,
                }
            )
            arrows.append(
                {"polygon": arrowhead(path), "color": [*color[:3], 210], "tooltip": tooltip}
            )
    for node in nodes.values():
        node["tooltip"] = (
            f"{node['name']}\nPickup quantity: {node['outbound']:g}\n"
            f"Dropoff quantity: {node['inbound']:g}\n{node['precision']}"
        )
    return {
        "lines": lines,
        "arrows": arrows,
        "nodes": list(nodes.values()),
        "missing": missing,
        "units_per_line": scale,
    }


def deck(data):
    layers = [
        pdk.Layer(
            "PathLayer",
            data["lines"],
            id="flows",
            get_path="path",
            get_color="color",
            get_width=1.3,
            width_units=pdk.types.String("pixels"),
            pickable=True,
        ),
        pdk.Layer(
            "PolygonLayer",
            data["arrows"],
            id="direction",
            get_polygon="polygon",
            get_fill_color="color",
            stroked=False,
            pickable=True,
        ),
        pdk.Layer(
            "ScatterplotLayer",
            data["nodes"],
            id="locations",
            get_position="position",
            get_fill_color=[18, 46, 68, 240],
            get_radius=4,
            radius_units=pdk.types.String("pixels"),
            pickable=True,
        ),
        pdk.Layer(
            "TextLayer",
            data["nodes"],
            id="labels",
            get_position="position",
            get_text="name",
            get_size=11,
            get_color=[18, 46, 68],
            get_pixel_offset=[0, 12],
            get_text_anchor=pdk.types.String("middle"),
        ),
    ]
    return pdk.Deck(
        layers=layers,
        initial_view_state=pdk.ViewState(latitude=-41.0, longitude=173.4, zoom=4.5, pitch=0),
        map_provider="carto",
        map_style="light",
        tooltip={"text": "{tooltip}", "style": {"fontSize": "13px"}},
    )
