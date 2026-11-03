import pytest

from stickman_desktop.environment import desktop_surfaces, nearest_monitor, virtual_bounds
from stickman_desktop.motion import Surface
from stickman_desktop.windows import MonitorInfo, WindowInfo


@pytest.fixture
def primary():
    return MonitorInfo((0, 0, 1200, 900), (0, 30, 1200, 860), True)


@pytest.fixture
def left():
    return MonitorInfo((-1000, -200, 0, 700), (-970, -200, 0, 660), False)


def windows_only(surfaces):
    return [surface for surface in surfaces if surface.kind == "window"]


def test_virtual_bounds_include_negative_origins_and_uneven_displays(primary, left):
    assert virtual_bounds([primary, left]) == (-1000, -200, 1200, 900)
    assert virtual_bounds([left, primary]) == (-1000, -200, 1200, 900)


def test_virtual_bounds_require_a_monitor():
    with pytest.raises(ValueError, match="monitor"):
        virtual_bounds([])


def test_nearest_monitor_uses_distance_to_work_area_in_display_gaps():
    first = MonitorInfo((0, 0, 600, 600), (0, 0, 600, 560), True)
    second = MonitorInfo((900, 300, 1500, 900), (900, 300, 1500, 860), False)

    assert nearest_monitor([first, second], 800, 400) is second
    assert nearest_monitor([first, second], 650, 50) is first
    assert nearest_monitor([first, second], 1100, 400) is second


def test_monitor_floors_use_work_areas_and_translate_the_virtual_origin(primary, left):
    surfaces = desktop_surfaces([primary, left], [], (-1000, -200))

    assert surfaces == [
        Surface(f"monitor:{primary.rect}", 1000, 2200, 1057, "floor"),
        Surface(f"monitor:{left.rect}", 30, 1000, 857, "floor"),
    ]


@pytest.mark.parametrize("top, width, eligible", [
    (133, 100, False),
    (134, 100, True),
    (200, 79, False),
    (200, 80, True),
    (836, 100, True),
    (837, 100, False),
])
def test_window_edges_require_headroom_width_and_clearance_above_floor(primary, top, width, eligible):
    window = WindowInfo(10, "Editor", (100, top, 100 + width, top + 100))

    surfaces = windows_only(desktop_surfaces([primary], [window], (0, 0)))

    assert bool(surfaces) is eligible
    if eligible:
        assert surfaces == [Surface("window:10", 100, 100 + width, top - 3)]


def test_window_edge_is_clipped_to_usable_monitor_area(primary, left):
    across_displays = WindowInfo(10, "Wide editor", (-1100, 200, 400, 600))

    surfaces = windows_only(desktop_surfaces([primary, left], [across_displays], (-1000, -200)))

    # Join the continuous edge across both displays without extending behind the left taskbar.
    assert surfaces == [Surface("window:10", 30, 1400, 397)]


def test_support_prefers_current_monitor_segment_in_local_coordinates(primary, left):
    across_displays = WindowInfo(10, "Wide editor", (-1100, 200, 400, 600))
    gap_left = MonitorInfo(left.rect, (-970, -200, -100, 660), False)

    surfaces = windows_only(desktop_surfaces(
        [primary, gap_left], [across_displays], (-1000, -200),
        support_key="window:10", character_x=1200,
    ))

    # Local X 1200 is global X 200, inside the narrower segment on the primary display.
    assert surfaces == [Surface("window:10", 1000, 1400, 397)]


def test_continuous_edge_across_adjacent_monitors_is_one_platform():
    first = MonitorInfo((0, 0, 1000, 900), (0, 0, 1000, 850), True)
    second = MonitorInfo((1000, 0, 2000, 900), (1000, 0, 2000, 850), False)
    window = WindowInfo(10, "Across displays", (100, 200, 1700, 600))

    surfaces = windows_only(desktop_surfaces([first, second], [window], (0, 0)))

    assert surfaces == [Surface("window:10", 100, 1700, 197)]


def test_real_gap_between_monitors_keeps_platform_segments_separate():
    first = MonitorInfo((0, 0, 1000, 900), (0, 0, 1000, 850), True)
    second = MonitorInfo((1100, 0, 2100, 900), (1100, 0, 2100, 850), False)
    window = WindowInfo(10, "Across gap", (100, 200, 1800, 600))

    default = windows_only(desktop_surfaces([first, second], [window], (0, 0)))
    standing_on_right = windows_only(desktop_surfaces(
        [first, second], [window], (0, 0), support_key="window:10", character_x=1500,
    ))

    assert default == [Surface("window:10", 100, 1000, 197)]
    assert standing_on_right == [Surface("window:10", 1100, 1800, 197)]


def test_catalog_removal_of_minimized_or_closed_window_removes_its_platform(primary):
    window = WindowInfo(10, "Editor", (100, 200, 800, 600))
    present = desktop_surfaces([primary], [window], (0, 0))
    removed = desktop_surfaces([primary], [], (0, 0))

    assert windows_only(present) == [Surface("window:10", 100, 800, 197)]
    assert windows_only(removed) == []
    assert [surface for surface in present if surface.kind == "floor"] == removed


def test_higher_window_can_cover_an_entire_lower_edge(primary):
    front = WindowInfo(20, "Front", (50, 150, 1000, 700))
    behind = WindowInfo(10, "Behind", (100, 300, 900, 750))

    surfaces = windows_only(desktop_surfaces([primary], [front, behind], (0, 0)))

    assert surfaces == [Surface("window:20", 50, 1000, 147)]


def test_partly_covered_edge_uses_the_widest_exposed_segment(primary):
    front = WindowInfo(20, "Front", (200, 150, 700, 600))
    behind = WindowInfo(10, "Behind", (100, 300, 900, 750))

    surfaces = windows_only(desktop_surfaces([primary], [front, behind], (0, 0)))

    assert surfaces == [
        Surface("window:20", 200, 700, 147),
        Surface("window:10", 700, 900, 297),
    ]


@pytest.mark.parametrize("support_key, character_x, expected", [
    ("window:10", 150, (100, 200)),
    ("window:10", 124, (100, 200)),
    ("window:10", 120, (700, 900)),
    ("window:20", 150, (700, 900)),
    (None, 150, (700, 900)),
])
def test_current_support_segment_is_preserved_only_with_room_for_character(
    primary, support_key, character_x, expected,
):
    front = WindowInfo(20, "Front", (200, 150, 700, 600))
    behind = WindowInfo(10, "Behind", (100, 300, 900, 750))

    surfaces = desktop_surfaces(
        [primary], [front, behind], (0, 0),
        support_key=support_key, character_x=character_x,
    )
    platform = next(surface for surface in surfaces if surface.key == "window:10")

    assert (platform.left, platform.right) == expected


def test_window_below_in_z_order_does_not_cover_a_higher_edge(primary):
    higher = WindowInfo(10, "Higher", (100, 300, 900, 750))
    lower = WindowInfo(20, "Lower", (50, 150, 1000, 700))

    surfaces = desktop_surfaces([primary], [higher, lower], (0, 0))

    assert next(surface for surface in surfaces if surface.key == "window:10") == Surface(
        "window:10", 100, 900, 297,
    )


def test_window_ending_at_an_edge_does_not_cover_that_edge(primary):
    front = WindowInfo(20, "Above", (50, 150, 1000, 300))
    behind = WindowInfo(10, "Below", (100, 300, 900, 750))

    surfaces = desktop_surfaces([primary], [front, behind], (0, 0))

    assert next(surface for surface in surfaces if surface.key == "window:10") == Surface(
        "window:10", 100, 900, 297,
    )


def test_occlusion_can_leave_only_fragments_too_narrow_for_a_platform(primary):
    front = WindowInfo(20, "Front", (179, 150, 421, 600))
    behind = WindowInfo(10, "Behind", (100, 300, 500, 750))

    surfaces = desktop_surfaces([primary], [front, behind], (0, 0))

    assert "window:10" not in {surface.key for surface in surfaces}


def test_platform_keys_survive_window_movement_and_taskbar_changes(primary):
    before = desktop_surfaces(
        [primary], [WindowInfo(10, "Before", (100, 200, 800, 600))], (0, 0),
    )
    moved_taskbar = MonitorInfo(primary.rect, (40, 0, 1200, 900), primary.primary)
    after = desktop_surfaces(
        [moved_taskbar], [WindowInfo(10, "Renamed", (200, 250, 900, 650))], (0, 0),
    )

    assert [surface.key for surface in before] == [surface.key for surface in after]
    assert before != after


@pytest.mark.parametrize("work_rect", [
    (0, 0, 1920, 1032),   # Bottom taskbar already removed by Windows.
    (48, 0, 1920, 1080),  # Left taskbar does not change the usable bottom.
    (0, 48, 1920, 1080),  # Top taskbar is already reflected in the work area.
])
def test_default_floor_touches_usable_bottom_without_subtracting_taskbar_twice(work_rect):
    monitor = MonitorInfo((0, 0, 1920, 1080), work_rect, True)
    floor, = desktop_surfaces([monitor], [], (0, 0))
    assert floor.y == work_rect[3] - 3
    assert (floor.left, floor.right) == (work_rect[0], work_rect[2])


def test_explicit_ground_offset_remains_additional_custom_clearance(primary):
    floor, = desktop_surfaces([primary], [], (0, 0), ground_offset=20)
    assert floor.y == primary.work_rect[3] - 20 - 3


def test_window_contact_accounts_for_rounded_foot_stroke(primary):
    window = WindowInfo(10, "Editor", (100, 200, 800, 600))
    platform, = windows_only(desktop_surfaces([primary], [window], (0, 0)))
    assert platform.y + 3 == window.rect[1]
