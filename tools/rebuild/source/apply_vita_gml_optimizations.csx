using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UndertaleModLib.Compiler;
using UndertaleModLib.Models;

EnsureDataLoaded();

var report = new List<string>();
report.Add("DeltaruneVita GML optimization report");
report.Add("Format: semantic resource names; no numeric room/code IDs");

bool HasRoom(string name)
{
    return Data.Rooms.Any(room => room?.Name?.Content == name);
}

bool PatchChapter2Rollercoaster()
{
    const string roomName = "room_dw_cyber_rollercoaster";
    const string codeName = "gml_GlobalScript_scr_draw_sprite_tiled_area";
    const string anchor = "var sh = sprite_get_height(sprite) * yscale;";
    const string marker = "if (room == room_dw_cyber_rollercoaster && view_camera[0] != -1)";
    const string replacement = @"var sh = sprite_get_height(sprite) * yscale;
    if (room == room_dw_cyber_rollercoaster && view_camera[0] != -1)
    {
        var _cam = view_camera[0];
        var _vx = camera_get_view_x(_cam);
        var _vy = camera_get_view_y(_cam);
        var _vw = camera_get_view_width(_cam);
        var _vh = camera_get_view_height(_cam);
        x1 = max(x1, _vx - sw);
        y1 = max(y1, _vy - sh);
        x2 = min(x2, _vx + _vw + sw);
        y2 = min(y2, _vy + _vh + sh);
    }";

    if (!HasRoom(roomName))
    {
        report.Add("SKIP chapter2_rollercoaster_culling: room absent");
        return false;
    }

    UndertaleCode code = Data.Code.ByName(codeName);
    if (code is null)
        throw new Exception("Chapter 2 room found, but code is absent: " + codeName);

    string source = GetDecompiledText(codeName);
    if (source.Contains(marker))
    {
        report.Add("PRESENT chapter2_rollercoaster_culling: already applied");
        return false;
    }
    if (!source.Contains(anchor))
        throw new Exception("Chapter 2 rollercoaster anchor not recognized; refusing an unsafe patch.");

    CodeImportGroup imports = new(Data, null, Data.ToolInfo.DecompilerSettings)
    {
        ThrowOnNoOpFindReplace = true,
        MainThreadAction = MainThreadAction
    };
    imports.QueueFindReplace(code, anchor, replacement, true);
    imports.Import();
    report.Add("APPLIED chapter2_rollercoaster_culling: tiled draw clipped to active camera");
    return true;
}

bool PatchChapter3CircleZoom()
{
    const string roomName = "room_dw_couch_overworld_01";
    const string stepName = "gml_Object_obj_circlezoom_Step_2";
    const string drawName = "gml_Object_obj_circlezoom_Draw_0";

    if (!HasRoom(roomName))
    {
        report.Add("SKIP chapter3_circlezoom: room absent");
        return false;
    }

    UndertaleCode stepCode = Data.Code.ByName(stepName);
    UndertaleCode drawCode = Data.Code.ByName(drawName);
    if (stepCode is null || drawCode is null)
        throw new Exception("Chapter 3 room found, but obj_circlezoom code is incomplete.");

    string step = GetDecompiledText(stepName);
    string draw = GetDecompiledText(drawName);
    bool halfSurface = step.Contains("surface_create(320, 240)");
    bool halfCadence = step.Contains("if ((siner % 2) == 0)")
        || step.Contains("if ((siner mod 2) == 0)");
    bool scaledDraw = draw.Contains(
        "draw_surface_ext(surf, camerax(), cameray(), 2, 2, 0, c_white, 1)"
    );

    if (halfSurface && halfCadence && scaledDraw)
    {
        report.Add("PRESENT chapter3_circlezoom: 320x240 surface at 30 Hz");
        return false;
    }
    if (halfSurface || halfCadence || scaledDraw)
        throw new Exception("Partial Chapter 3 circle-zoom patch detected; refusing mixed state.");

    string surfaceAnchor = step.Contains("surface_create(640, 480)")
        ? "surf = surface_create(640, 480);"
        : "surf = surface_create(room_width, room_height);";
    string rectangleAnchor = step.Contains("draw_rectangle(0, 0, 640, 480, false);")
        ? "draw_rectangle(0, 0, 640, 480, false);"
        : "draw_rectangle(0, 0, camerax() + 700, cameray() + 500, false);";
    string circle0 = step.Contains("draw_circle(x - camerax(), y - cameray(), radius, false);")
        ? "draw_circle(x - camerax(), y - cameray(), radius, false);"
        : "draw_circle(x, y, radius, false);";
    string circle20 = step.Contains("draw_circle(x - camerax(), y - cameray(), radius + 20, false);")
        ? "draw_circle(x - camerax(), y - cameray(), radius + 20, false);"
        : "draw_circle(x, y, radius + 20, false);";
    string circle40 = step.Contains("draw_circle(x - camerax(), y - cameray(), radius + 40, false);")
        ? "draw_circle(x - camerax(), y - cameray(), radius + 40, false);"
        : "draw_circle(x, y, radius + 40, false);";
    string drawAnchor = draw.Contains("draw_surface(surf, camerax(), cameray());")
        ? "draw_surface(surf, camerax(), cameray());"
        : "draw_surface(surf, 0, 0);";

    string[] required = new string[] {
        surfaceAnchor, rectangleAnchor, circle0, circle20, circle40,
        "surface_set_target(surf);", drawAnchor
    };
    foreach (string anchor in required)
    {
        if (!step.Contains(anchor) && !draw.Contains(anchor))
            throw new Exception("Chapter 3 circle-zoom anchor not recognized: " + anchor);
    }

    CodeImportGroup imports = new(Data, null, Data.ToolInfo.DecompilerSettings)
    {
        ThrowOnNoOpFindReplace = true,
        MainThreadAction = MainThreadAction
    };
    imports.QueueFindReplace(stepCode, surfaceAnchor,
        "surf = surface_create(320, 240);", true);
    imports.QueueFindReplace(stepCode, "surface_set_target(surf);",
        "if ((siner mod 2) == 0) exit;\n"
        + "surface_set_target(surf);\n"
        + "draw_clear_alpha(c_black, 0);", true);
    imports.QueueFindReplace(stepCode, rectangleAnchor,
        "draw_rectangle(0, 0, 320, 240, false);", true);
    imports.QueueFindReplace(stepCode, circle0,
        "draw_circle((x - camerax()) / 2, (y - cameray()) / 2, radius / 2, false);", true);
    imports.QueueFindReplace(stepCode, circle20,
        "draw_circle((x - camerax()) / 2, (y - cameray()) / 2, (radius + 20) / 2, false);", true);
    imports.QueueFindReplace(stepCode, circle40,
        "draw_circle((x - camerax()) / 2, (y - cameray()) / 2, (radius + 40) / 2, false);", true);
    imports.QueueFindReplace(drawCode, drawAnchor,
        "draw_surface_ext(surf, camerax(), cameray(), 2, 2, 0, c_white, 1);", true);
    imports.Import();

    report.Add("APPLIED chapter3_circlezoom: 320x240 surface at 30 Hz");
    return true;
}

bool changed = false;

bool PatchGameOverBlackBackground()
{
    const string codeName = "gml_Object_obj_gameover_init_Create_0";
    const string anchor = "bg = scr_marker(0, 0, global.screenshot);";
    const string replacement = "bg = noone;";
    UndertaleCode code = Data.Code.ByName(codeName);
    if (!HasRoom("room_gameover") || code is null)
    {
        report.Add("SKIP gameover_black_background: room/code absent");
        return false;
    }

    string source = GetDecompiledText(codeName);
    if (source.Contains(replacement) || source.Contains("bg = -4;"))
    {
        report.Add("PRESENT gameover_black_background: captured room frame suppressed");
        return false;
    }
    if (!source.Contains(anchor))
        throw new Exception("Game Over background anchor not recognized; refusing an unsafe patch.");

    CodeImportGroup imports = new(Data, null, Data.ToolInfo.DecompilerSettings)
    {
        ThrowOnNoOpFindReplace = true,
        MainThreadAction = MainThreadAction
    };
    imports.QueueFindReplace(code, anchor, replacement, true);
    imports.Import();
    report.Add("APPLIED gameover_black_background: captured room frame suppressed");
    return true;
}

bool PatchChapter0PortVersion()
{
    // Chapter 0 is the chapter selector. Store a stable marker in every
    // language variant; the Vita runner replaces it from the single
    // app0:assets/build_version.txt shipped by the VPK.
    bool isChapter0 = HasRoom("PLACE_CHAPTER_SELECT_2X") ||
                      HasRoom("PLACE_CHAPTER_SELECT") ||
                      HasRoom("ROOM_INITIALIZE_CHAPTER_SELECT");
    if (!isChapter0)
    {
        report.Add("SKIP chapter0_port_version: chapter selector absent");
        return false;
    }

    bool localChanged = false;
    foreach (UndertaleString item in Data.Strings)
    {
        string value = item?.Content;
        if (String.IsNullOrWhiteSpace(value)) continue;
        if (value.Contains("{PORT_VERSION}")) continue;
        if (value.Contains("DELTARUNE VITA v0.") ||
            value.Contains("DELTARUNE v0.68 (Internal Build)") ||
            value.Contains("v0.68 - Wolff"))
        {
            item.Content = "DELTARUNE VITA {PORT_VERSION}";
            localChanged = true;
        }
    }
    report.Add((localChanged ? "APPLIED" : "PRESENT") +
               " chapter0_port_version: shared VPK marker");
    return localChanged;
}

changed |= PatchChapter0PortVersion();
changed |= PatchGameOverBlackBackground();
changed |= PatchChapter2Rollercoaster();
changed |= PatchChapter3CircleZoom();

report.Add("RESULT changed=" + (changed ? "1" : "0"));

string reportPath = Environment.GetEnvironmentVariable("DELTARUNE_VITA_GML_REPORT");
if (!String.IsNullOrWhiteSpace(reportPath))
{
    string parent = Path.GetDirectoryName(reportPath);
    if (!String.IsNullOrWhiteSpace(parent)) Directory.CreateDirectory(parent);
    File.WriteAllLines(reportPath, report);
}

foreach (string line in report) ScriptMessage(line);
