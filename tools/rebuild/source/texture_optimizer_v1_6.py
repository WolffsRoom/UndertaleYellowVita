import argparse
import csv
import hashlib
import json
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

PIPELINE_VERSION = "1.6.0"

V3_SOURCE = 'import csv\nimport json\nimport shutil\nimport subprocess\nimport sys\nfrom collections import defaultdict\nfrom pathlib import Path\n\nDATA_WIN = Path(r"C:\\Users\\385090\\Downloads\\deltarune\\Teste\\data.win")\nCLI_FOLDER = Path(r"C:\\Users\\385090\\Downloads\\deltarune\\Teste\\UTMT_CLI_v0.9.1.2-Windows")\nOUTPUT_DIR = DATA_WIN.parent / "vita_texture_analysis_v3"\n\nLARGE_DIMENSION = 1024\nATLAS_SIZES = [128, 256, 512, 1024, 2048]\n\nHIGH_ESCAPE_RATIO = 0.60\nMEDIUM_ESCAPE_RATIO = 0.30\nKEEP_WITH_ANCHOR_RATIO = 0.80\nMIN_HIGH_VALUE_ESCAPE_ROOMS = 3\n\nBYTES_PER_PIXEL = {\n    "RGBA8888": 4.0,\n    "RGBA4444": 2.0,\n    "BC3": 1.0,\n    "BC1": 0.5,\n}\n\nCSX_TEMPLATE = r\'\'\'\nusing System;\nusing System.IO;\nusing System.Text;\nusing System.Linq;\nusing System.Collections;\nusing System.Collections.Generic;\nusing System.Reflection;\nusing UndertaleModLib.Models;\n\nstring outputPath = @"__OUTPUT_JSON__";\nint largeDimension = __LARGE_DIM__;\n\nstring GetName(object obj)\n{\n    if (obj == null) return null;\n    try\n    {\n        PropertyInfo p = obj.GetType().GetProperty("Name");\n        if (p == null) return null;\n        object value = p.GetValue(obj);\n        if (value == null) return null;\n        PropertyInfo cp = value.GetType().GetProperty("Content");\n        if (cp != null)\n        {\n            object content = cp.GetValue(value);\n            return content == null ? null : content.ToString();\n        }\n        return value.ToString();\n    }\n    catch { return null; }\n}\n\nobject GetProp(object obj, string property)\n{\n    if (obj == null) return null;\n    try\n    {\n        PropertyInfo p = obj.GetType().GetProperty(\n            property, BindingFlags.Public | BindingFlags.Instance\n        );\n        return p == null ? null : p.GetValue(obj);\n    }\n    catch { return null; }\n}\n\nint RefIndex(IEnumerable list, object target)\n{\n    if (target == null) return -1;\n    int i = 0;\n    foreach (object item in list)\n    {\n        if (Object.ReferenceEquals(item, target)) return i;\n        i++;\n    }\n    return -1;\n}\n\nstring TypeName(object obj)\n{\n    return obj == null ? null : obj.GetType().Name;\n}\n\nDictionary<int, List<Dictionary<string, object>>> itemResources =\n    new Dictionary<int, List<Dictionary<string, object>>>();\n\nHashSet<string> resourceDedup = new HashSet<string>();\n\nvoid RegisterResourceRef(int itemIndex, string category, string collection,\n                         string resourceName, string resourceType)\n{\n    if (itemIndex < 0) return;\n\n    if (!itemResources.ContainsKey(itemIndex))\n        itemResources[itemIndex] = new List<Dictionary<string, object>>();\n\n    string key = itemIndex + "|" + category + "|" + collection + "|" +\n                 resourceName + "|" + resourceType;\n\n    if (resourceDedup.Contains(key)) return;\n    resourceDedup.Add(key);\n\n    itemResources[itemIndex].Add(new Dictionary<string, object>\n    {\n        ["category"] = category,\n        ["collection"] = collection,\n        ["resource"] = resourceName,\n        ["resource_type"] = resourceType\n    });\n}\n\nvoid ScanForTPI(object value, HashSet<object> visited, int depth, int maxDepth,\n                string category, string collection, string resourceName,\n                string resourceType)\n{\n    if (value == null || depth > maxDepth) return;\n\n    if (value is UndertaleTexturePageItem)\n    {\n        int idx = RefIndex(Data.TexturePageItems, value);\n        RegisterResourceRef(idx, category, collection, resourceName, resourceType);\n        return;\n    }\n\n    Type t = value.GetType();\n\n    if (t.IsPrimitive || t.IsEnum || value is string ||\n        value is UndertaleString || value is decimal)\n        return;\n\n    if (TypeName(value) == "UndertaleData") return;\n\n    if (!t.IsValueType)\n    {\n        if (visited.Contains(value)) return;\n        visited.Add(value);\n    }\n\n    if (value is IEnumerable && !(value is string))\n    {\n        int safety = 0;\n        foreach (object child in (IEnumerable)value)\n        {\n            if (safety++ > 30000) break;\n            ScanForTPI(child, visited, depth + 1, maxDepth,\n                       category, collection, resourceName, resourceType);\n        }\n        return;\n    }\n\n    foreach (PropertyInfo p in t.GetProperties(\n        BindingFlags.Public | BindingFlags.Instance))\n    {\n        if (!p.CanRead || p.GetIndexParameters().Length != 0) continue;\n\n        string pn = p.Name;\n        if (pn == "Name" || pn == "Code" || pn == "Bytecode" ||\n            pn == "Data" || pn == "ParentEntry" ||\n            pn == "ObjectDefinition" || pn == "ParentId")\n            continue;\n\n        object child = null;\n        try { child = p.GetValue(value); }\n        catch { continue; }\n\n        if (child == null) continue;\n\n        ScanForTPI(child, visited, depth + 1, maxDepth,\n                   category, collection, resourceName, resourceType);\n    }\n}\n\nstring CategoryForCollection(string collection, string resourceName)\n{\n    string c = (collection ?? "").ToLowerInvariant();\n    string n = (resourceName ?? "").ToLowerInvariant();\n\n    if (c.Contains("font") || n.StartsWith("font_") ||\n        n.StartsWith("fnt_") || n.Contains("_font"))\n        return "FONT";\n\n    if (c.Contains("tileset") || n.Contains("tileset") ||\n        n.Contains("tile_set") || n.Contains("_tiles"))\n        return "TILESET";\n\n    if (c.Contains("sprite")) return "SPRITE";\n\n    if (c.Contains("background"))\n    {\n        if (n.Contains("tileset") || n.Contains("_tiles"))\n            return "TILESET";\n        return "BACKGROUND";\n    }\n\n    if (c.Contains("sequence")) return "SEQUENCE";\n\n    return "OTHER";\n}\n\nvoid ScanTopCollection(string propertyName, int maxDepth)\n{\n    object collectionObj = GetProp(Data, propertyName);\n    if (!(collectionObj is IEnumerable)) return;\n\n    foreach (object resource in (IEnumerable)collectionObj)\n    {\n        if (resource == null) continue;\n\n        string rn = GetName(resource);\n        if (String.IsNullOrEmpty(rn)) rn = TypeName(resource);\n\n        string category = CategoryForCollection(propertyName, rn);\n\n        ScanForTPI(resource, new HashSet<object>(), 0, maxDepth,\n                   category, propertyName, rn, TypeName(resource));\n    }\n}\n\nstring[] collections =\n{\n    "Sprites", "Backgrounds", "Fonts", "TileSets", "Tilesets", "Sequences"\n};\n\nforeach (string collection in collections)\n    ScanTopCollection(collection, 7);\n\nList<Dictionary<string, object>> itemsInfo =\n    new List<Dictionary<string, object>>();\n\nList<Dictionary<string, object>> pagesInfo =\n    new List<Dictionary<string, object>>();\n\nfor (int pageIndex = 0; pageIndex < Data.EmbeddedTextures.Count; pageIndex++)\n{\n    object page = Data.EmbeddedTextures[pageIndex];\n    int maxX = 0;\n    int maxY = 0;\n    List<int> pageItems = new List<int>();\n\n    for (int i = 0; i < Data.TexturePageItems.Count; i++)\n    {\n        UndertaleTexturePageItem item = Data.TexturePageItems[i];\n\n        if (item == null ||\n            !Object.ReferenceEquals(item.TexturePage, page))\n            continue;\n\n        int w = item.SourceWidth;\n        int h = item.SourceHeight;\n\n        maxX = Math.Max(maxX, item.SourceX + w);\n        maxY = Math.Max(maxY, item.SourceY + h);\n        pageItems.Add(i);\n\n        List<Dictionary<string, object>> refs =\n            itemResources.ContainsKey(i)\n            ? itemResources[i]\n            : new List<Dictionary<string, object>>();\n\n        itemsInfo.Add(new Dictionary<string, object>\n        {\n            ["item"] = i,\n            ["page"] = pageIndex,\n            ["source_x"] = item.SourceX,\n            ["source_y"] = item.SourceY,\n            ["width"] = w,\n            ["height"] = h,\n            ["area"] = (long)w * (long)h,\n            ["large"] = (w > largeDimension || h > largeDimension),\n            ["resources"] = refs\n        });\n    }\n\n    pagesInfo.Add(new Dictionary<string, object>\n    {\n        ["page"] = pageIndex,\n        ["name"] = GetName(page) ?? ("Texture_" + pageIndex),\n        ["estimated_width"] = maxX,\n        ["estimated_height"] = maxY,\n        ["item_count"] = pageItems.Count,\n        ["texture_items"] = pageItems\n    });\n}\n\nvoid AddTPIToRoom(UndertaleTexturePageItem item,\n                  HashSet<int> usedItems,\n                  HashSet<int> usedPages,\n                  Dictionary<int, HashSet<int>> perPage)\n{\n    if (item == null) return;\n\n    int ti = RefIndex(Data.TexturePageItems, item);\n    int pi = RefIndex(Data.EmbeddedTextures, item.TexturePage);\n\n    if (ti >= 0) usedItems.Add(ti);\n\n    if (pi >= 0)\n    {\n        usedPages.Add(pi);\n        if (!perPage.ContainsKey(pi))\n            perPage[pi] = new HashSet<int>();\n        if (ti >= 0)\n            perPage[pi].Add(ti);\n    }\n}\n\nvoid AddSpriteToRoom(UndertaleSprite sprite,\n                     HashSet<int> usedItems,\n                     HashSet<int> usedPages,\n                     Dictionary<int, HashSet<int>> perPage)\n{\n    if (sprite == null || sprite.Textures == null) return;\n\n    foreach (UndertaleSprite.TextureEntry entry in sprite.Textures)\n    {\n        if (entry != null && entry.Texture != null)\n            AddTPIToRoom(entry.Texture, usedItems, usedPages, perPage);\n    }\n}\n\nvoid AddBackgroundToRoom(UndertaleBackground bg,\n                         HashSet<int> usedItems,\n                         HashSet<int> usedPages,\n                         Dictionary<int, HashSet<int>> perPage)\n{\n    if (bg != null && bg.Texture != null)\n        AddTPIToRoom(bg.Texture, usedItems, usedPages, perPage);\n}\n\nvoid ScanRoomGraph(object value, HashSet<object> visited, int depth,\n                   HashSet<int> usedItems, HashSet<int> usedPages,\n                   Dictionary<int, HashSet<int>> perPage)\n{\n    if (value == null || depth > 7) return;\n\n    if (value is UndertaleTexturePageItem)\n    {\n        AddTPIToRoom((UndertaleTexturePageItem)value,\n                     usedItems, usedPages, perPage);\n        return;\n    }\n\n    if (value is UndertaleSprite)\n    {\n        AddSpriteToRoom((UndertaleSprite)value,\n                        usedItems, usedPages, perPage);\n        return;\n    }\n\n    if (value is UndertaleBackground)\n    {\n        AddBackgroundToRoom((UndertaleBackground)value,\n                            usedItems, usedPages, perPage);\n        return;\n    }\n\n    Type t = value.GetType();\n\n    if (t.IsPrimitive || t.IsEnum || value is string ||\n        value is UndertaleString)\n        return;\n\n    if (TypeName(value) == "UndertaleData") return;\n\n    if (!t.IsValueType)\n    {\n        if (visited.Contains(value)) return;\n        visited.Add(value);\n    }\n\n    if (value is IEnumerable && !(value is string))\n    {\n        int safety = 0;\n        foreach (object child in (IEnumerable)value)\n        {\n            if (safety++ > 50000) break;\n            ScanRoomGraph(child, visited, depth + 1,\n                          usedItems, usedPages, perPage);\n        }\n        return;\n    }\n\n    string[] props =\n    {\n        "Sprite", "Background", "BackgroundDefinition", "AssetsData",\n        "BackgroundData", "TilesData", "LegacyTiles", "Sprites",\n        "Sequences", "Layers"\n    };\n\n    foreach (string pn in props)\n    {\n        object child = GetProp(value, pn);\n        if (child == null) continue;\n\n        ScanRoomGraph(child, visited, depth + 1,\n                      usedItems, usedPages, perPage);\n    }\n}\n\nList<Dictionary<string, object>> roomsInfo =\n    new List<Dictionary<string, object>>();\n\nfor (int r = 0; r < Data.Rooms.Count; r++)\n{\n    UndertaleRoom room = Data.Rooms[r];\n\n    HashSet<int> usedItems = new HashSet<int>();\n    HashSet<int> usedPages = new HashSet<int>();\n    Dictionary<int, HashSet<int>> perPage =\n        new Dictionary<int, HashSet<int>>();\n\n    if (room.GameObjects != null)\n    {\n        foreach (UndertaleRoom.GameObject inst in room.GameObjects)\n        {\n            if (inst == null || inst.ObjectDefinition == null) continue;\n\n            UndertaleGameObject obj = inst.ObjectDefinition;\n\n            if (obj.Sprite != null)\n                AddSpriteToRoom(obj.Sprite, usedItems, usedPages, perPage);\n\n            try\n            {\n                if (obj.TextureMaskId != null)\n                    AddSpriteToRoom(obj.TextureMaskId,\n                                    usedItems, usedPages, perPage);\n            }\n            catch {}\n        }\n    }\n\n    try\n    {\n        ScanRoomGraph(room.Layers, new HashSet<object>(), 0,\n                      usedItems, usedPages, perPage);\n    }\n    catch {}\n\n    if (room.Backgrounds != null)\n    {\n        foreach (UndertaleRoom.Background rb in room.Backgrounds)\n        {\n            if (rb != null && rb.Enabled &&\n                rb.BackgroundDefinition != null)\n                AddBackgroundToRoom(rb.BackgroundDefinition,\n                                    usedItems, usedPages, perPage);\n        }\n    }\n\n    if (room.Tiles != null)\n    {\n        foreach (UndertaleRoom.Tile tile in room.Tiles)\n        {\n            if (tile != null && tile.BackgroundDefinition != null)\n                AddBackgroundToRoom(tile.BackgroundDefinition,\n                                    usedItems, usedPages, perPage);\n        }\n    }\n\n    List<Dictionary<string, object>> pageItems =\n        new List<Dictionary<string, object>>();\n\n    foreach (KeyValuePair<int, HashSet<int>> pair\n             in perPage.OrderBy(x => x.Key))\n    {\n        pageItems.Add(new Dictionary<string, object>\n        {\n            ["page"] = pair.Key,\n            ["used_texture_items"] = pair.Value.OrderBy(x => x).ToList()\n        });\n    }\n\n    roomsInfo.Add(new Dictionary<string, object>\n    {\n        ["room_index"] = r,\n        ["room"] = GetName(room) ?? ("Room_" + r),\n        ["pages"] = usedPages.OrderBy(x => x).ToList(),\n        ["texture_items"] = usedItems.OrderBy(x => x).ToList(),\n        ["page_items"] = pageItems\n    });\n}\n\nstring EscapeJson(string text)\n{\n    if (text == null) return "null";\n\n    StringBuilder sb = new StringBuilder();\n    sb.Append(\'"\');\n\n    foreach (char c in text)\n    {\n        switch (c)\n        {\n            case \'\\\\\': sb.Append("\\\\\\\\"); break;\n            case \'"\': sb.Append("\\\\\\""); break;\n            case \'\\n\': sb.Append("\\\\n"); break;\n            case \'\\r\': sb.Append("\\\\r"); break;\n            case \'\\t\': sb.Append("\\\\t"); break;\n            default:\n                if (c < 32)\n                    sb.Append("\\\\u" + ((int)c).ToString("x4"));\n                else\n                    sb.Append(c);\n                break;\n        }\n    }\n\n    sb.Append(\'"\');\n    return sb.ToString();\n}\n\nstring ToJson(object value)\n{\n    if (value == null) return "null";\n    if (value is string) return EscapeJson((string)value);\n    if (value is bool) return (bool)value ? "true" : "false";\n\n    if (value is IDictionary)\n    {\n        List<string> parts = new List<string>();\n        foreach (DictionaryEntry entry in (IDictionary)value)\n            parts.Add(EscapeJson(entry.Key.ToString()) + ":" +\n                      ToJson(entry.Value));\n        return "{" + String.Join(",", parts) + "}";\n    }\n\n    if (value is IEnumerable && !(value is string))\n    {\n        List<string> parts = new List<string>();\n        foreach (object item in (IEnumerable)value)\n            parts.Add(ToJson(item));\n        return "[" + String.Join(",", parts) + "]";\n    }\n\n    if (value is IFormattable)\n        return ((IFormattable)value).ToString(\n            null,\n            System.Globalization.CultureInfo.InvariantCulture\n        );\n\n    return EscapeJson(value.ToString());\n}\n\nDictionary<string, object> root = new Dictionary<string, object>\n{\n    ["pages"] = pagesInfo,\n    ["items"] = itemsInfo,\n    ["rooms"] = roomsInfo\n};\n\nFile.WriteAllText(outputPath, ToJson(root), Encoding.UTF8);\nScriptMessage("Texture Repack Analyzer v3 extraction complete.\\n" + outputPath);\n\'\'\'\n\ndef find_cli():\n    for name in ("UndertaleModCli.exe", "UndertaleModCLI.exe"):\n        direct = CLI_FOLDER / name\n        if direct.exists():\n            return direct\n\n    if CLI_FOLDER.exists():\n        for name in ("UndertaleModCli.exe", "UndertaleModCLI.exe"):\n            matches = list(CLI_FOLDER.rglob(name))\n            if matches:\n                return matches[0]\n\n    for name in ("UndertaleModCli.exe", "UndertaleModCLI.exe"):\n        hit = shutil.which(name)\n        if hit:\n            return Path(hit)\n\n    return None\n\n\ndef write_csx():\n    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)\n\n    raw_json = OUTPUT_DIR / "raw_texture_analysis_v3.json"\n    csx = OUTPUT_DIR / "_texture_repack_analyzer_v3.csx"\n\n    content = (\n        CSX_TEMPLATE\n        .replace("__OUTPUT_JSON__", str(raw_json).replace(\'"\', \'""\'))\n        .replace("__LARGE_DIM__", str(LARGE_DIMENSION))\n    )\n\n    csx.write_text(content, encoding="utf-8")\n    return csx, raw_json\n\n\ndef run_cli(cli, csx):\n    cmd = [str(cli), "load", str(DATA_WIN), "-s", str(csx)]\n\n    print("=" * 96)\n    print("DELTARUNEVITA - TEXTURE REPACK ANALYZER V3")\n    print("=" * 96)\n    print(f"data.win : {DATA_WIN}")\n    print(f"CLI      : {cli}")\n    print(f"Saida    : {OUTPUT_DIR}")\n    print()\n    print("Extraindo estrutura do data.win...")\n    print()\n\n    result = subprocess.run(\n        cmd,\n        cwd=str(cli.parent),\n        stdout=subprocess.PIPE,\n        stderr=subprocess.STDOUT,\n        text=True,\n        encoding="utf-8",\n        errors="replace",\n    )\n\n    print(result.stdout)\n\n    if result.returncode != 0:\n        raise RuntimeError(\n            f"UndertaleModCLI terminou com codigo {result.returncode}"\n        )\n\n\ndef resource_key(ref):\n    return (\n        str(ref.get("category", "OTHER")),\n        str(ref.get("resource", "?")),\n    )\n\n\ndef resource_label(key):\n    return f"{key[0]}:{key[1]}"\n\n\ndef choose_min_atlas_size(total_area, max_w, max_h, packing_efficiency=0.80):\n    needed_area = total_area / max(packing_efficiency, 0.01)\n\n    for size in ATLAS_SIZES:\n        if max_w <= size and max_h <= size and needed_area <= size * size:\n            return size\n\n    return None\n\n\ndef atlas_vram_mib(size, fmt):\n    if size is None:\n        return None\n    return (size * size * BYTES_PER_PIXEL[fmt]) / (1024 * 1024)\n\n\ndef build_reports(raw_json):\n    data = json.loads(raw_json.read_text(encoding="utf-8-sig"))\n\n    pages = data["pages"]\n    items = data["items"]\n    rooms = data["rooms"]\n\n    page_by_id = {int(p["page"]): p for p in pages}\n    item_by_id = {int(i["item"]): i for i in items}\n\n    items_by_page = defaultdict(set)\n    resource_items = defaultdict(set)\n    item_resource_keys = defaultdict(set)\n\n    for item in items:\n        item_id = int(item["item"])\n        page_id = int(item["page"])\n        items_by_page[page_id].add(item_id)\n\n        for ref in item.get("resources", []):\n            key = resource_key(ref)\n            resource_items[key].add(item_id)\n            item_resource_keys[item_id].add(key)\n\n    room_page_items = defaultdict(lambda: defaultdict(set))\n    rooms_by_item = defaultdict(set)\n\n    for room in rooms:\n        room_name = room["room"]\n\n        for entry in room.get("page_items", []):\n            page_id = int(entry["page"])\n            used = {int(x) for x in entry["used_texture_items"]}\n\n            room_page_items[room_name][page_id].update(used)\n\n            for item_id in used:\n                rooms_by_item[item_id].add(room_name)\n\n    # Anchors are Texture Items exceeding 1024 in at least one dimension.\n    page_anchor_items = defaultdict(set)\n    page_anchor_resources = defaultdict(set)\n\n    for item_id, item in item_by_id.items():\n        if not bool(item.get("large", False)):\n            continue\n\n        page_id = int(item["page"])\n        page_anchor_items[page_id].add(item_id)\n\n        for key in item_resource_keys.get(item_id, set()):\n            page_anchor_resources[page_id].add(key)\n\n    anchored_pages = sorted(\n        page_id for page_id in page_by_id if page_anchor_items.get(page_id)\n    )\n\n    # ---------------------------------------------------------------------\n    # Page-level anchor analysis\n    # ---------------------------------------------------------------------\n\n    anchor_page_rows = []\n\n    for page_id in anchored_pages:\n        page_rooms = {\n            room_name\n            for room_name, per_page in room_page_items.items()\n            if per_page.get(page_id)\n        }\n\n        anchor_rooms = {\n            room_name\n            for room_name in page_rooms\n            if room_page_items[room_name][page_id] & page_anchor_items[page_id]\n        }\n\n        without_anchor = page_rooms - anchor_rooms\n\n        anchor_page_rows.append({\n            "page": page_id,\n            "anchors": sorted(page_anchor_items[page_id]),\n            "anchor_resources": sorted(\n                resource_label(k) for k in page_anchor_resources[page_id]\n            ),\n            "rooms_page": len(page_rooms),\n            "rooms_anchor": len(anchor_rooms),\n            "rooms_without_anchor": len(without_anchor),\n            "without_anchor_ratio": (\n                len(without_anchor) / len(page_rooms) if page_rooms else 0.0\n            ),\n        })\n\n    with (OUTPUT_DIR / "anchor_pages.csv").open(\n        "w", newline="", encoding="utf-8-sig"\n    ) as f:\n        w = csv.writer(f, delimiter=";")\n        w.writerow([\n            "page",\n            "anchor_items",\n            "anchor_resources",\n            "rooms_using_page",\n            "rooms_using_anchor",\n            "rooms_without_anchor",\n            "without_anchor_ratio",\n            "opportunity",\n        ])\n\n        for row in sorted(\n            anchor_page_rows,\n            key=lambda x: -x["without_anchor_ratio"],\n        ):\n            ratio = row["without_anchor_ratio"]\n\n            if ratio >= 0.60:\n                opportunity = "HIGH"\n            elif ratio >= 0.30:\n                opportunity = "MEDIUM"\n            else:\n                opportunity = "LOW"\n\n            w.writerow([\n                row["page"],\n                ",".join(map(str, row["anchors"])),\n                " | ".join(row["anchor_resources"]),\n                row["rooms_page"],\n                row["rooms_anchor"],\n                row["rooms_without_anchor"],\n                f"{ratio:.4f}",\n                opportunity,\n            ])\n\n    # ---------------------------------------------------------------------\n    # Resource-level KEEP / MOVE / DUPLICATE / GROUP\n    # ---------------------------------------------------------------------\n\n    decisions = []\n\n    for page_id in anchored_pages:\n        page_items = items_by_page[page_id]\n        anchors = page_anchor_items[page_id]\n\n        resources_on_page = set()\n        for item_id in page_items:\n            resources_on_page.update(item_resource_keys.get(item_id, set()))\n\n        for resource in sorted(resources_on_page):\n            resource_page_items = resource_items[resource] & page_items\n\n            if not resource_page_items:\n                continue\n\n            is_anchor = bool(resource_page_items & anchors)\n\n            rooms_using = set()\n            rooms_with_anchor = set()\n            rooms_without_anchor = set()\n            escape_rooms = set()\n            partial_rooms = set()\n\n            for room_name, per_page in room_page_items.items():\n                used = per_page.get(page_id, set())\n\n                if not (used & resource_page_items):\n                    continue\n\n                rooms_using.add(room_name)\n\n                if used & anchors:\n                    rooms_with_anchor.add(room_name)\n                    continue\n\n                rooms_without_anchor.add(room_name)\n\n                # Crucial v3 test:\n                # If every item used by the room on this page belongs to the\n                # candidate resource, cloning/moving that resource alone can\n                # remove the original page from this room.\n                remaining = used - resource_page_items\n\n                if not remaining:\n                    escape_rooms.add(room_name)\n                else:\n                    partial_rooms.add(room_name)\n\n            total_rooms = len(rooms_using)\n            anchor_count = len(rooms_with_anchor)\n            no_anchor_count = len(rooms_without_anchor)\n            escape_count = len(escape_rooms)\n            partial_count = len(partial_rooms)\n\n            anchor_ratio = anchor_count / total_rooms if total_rooms else 0.0\n            no_anchor_ratio = no_anchor_count / total_rooms if total_rooms else 0.0\n            escape_ratio = escape_count / total_rooms if total_rooms else 0.0\n\n            total_area = 0\n            max_w = 0\n            max_h = 0\n\n            for item_id in resource_page_items:\n                item = item_by_id[item_id]\n                total_area += int(item["area"])\n                max_w = max(max_w, int(item["width"]))\n                max_h = max(max_h, int(item["height"]))\n\n            min_atlas = choose_min_atlas_size(\n                total_area, max_w, max_h\n            )\n\n            category, name = resource\n\n            if is_anchor:\n                decision = "ANCHOR_KEEP"\n                reason = "O recurso e um anchor grande da pagina."\n\n            elif total_rooms == 0:\n                decision = "STATIC_REVIEW"\n                reason = "Nenhum uso estatico por room foi detectado."\n\n            elif anchor_ratio >= KEEP_WITH_ANCHOR_RATIO:\n                decision = "KEEP"\n                reason = "Quase sempre e usado junto com o anchor."\n\n            elif (\n                escape_count >= MIN_HIGH_VALUE_ESCAPE_ROOMS\n                and escape_ratio >= HIGH_ESCAPE_RATIO\n                and min_atlas is not None\n                and min_atlas <= 1024\n            ):\n                decision = "DUPLICATE_HIGH_VALUE"\n                reason = (\n                    "Clone pequeno permite que muitas rooms eliminem "\n                    "a pagina original."\n                )\n\n            elif (\n                escape_count > 0\n                and escape_ratio >= MEDIUM_ESCAPE_RATIO\n                and min_atlas is not None\n                and min_atlas <= 1024\n            ):\n                decision = "DUPLICATE_CANDIDATE"\n                reason = "Ha ganho direto em parte das rooms."\n\n            elif no_anchor_count > 0 and partial_count > 0:\n                decision = "GROUP_REPACK"\n                reason = (\n                    "O recurso aparece sem anchor, mas a room ainda usa "\n                    "outros recursos da mesma pagina."\n                )\n\n            else:\n                decision = "KEEP_REVIEW"\n                reason = "Nao ha evidencia suficiente para isolamento."\n\n            move_candidate = (\n                not is_anchor\n                and total_rooms > 0\n                and anchor_ratio <= 0.10\n                and no_anchor_count > 0\n                and min_atlas is not None\n                and min_atlas <= 1024\n            )\n\n            decisions.append({\n                "page": page_id,\n                "category": category,\n                "resource": name,\n                "items": sorted(resource_page_items),\n                "item_count": len(resource_page_items),\n                "total_area": total_area,\n                "max_w": max_w,\n                "max_h": max_h,\n                "min_atlas": min_atlas,\n                "rooms_using": total_rooms,\n                "with_anchor": anchor_count,\n                "without_anchor": no_anchor_count,\n                "escape": escape_count,\n                "partial": partial_count,\n                "anchor_ratio": anchor_ratio,\n                "no_anchor_ratio": no_anchor_ratio,\n                "escape_ratio": escape_ratio,\n                "decision": decision,\n                "reason": reason,\n                "move_candidate": move_candidate,\n                "escape_room_names": sorted(escape_rooms),\n            })\n\n    priority = {\n        "DUPLICATE_HIGH_VALUE": 0,\n        "DUPLICATE_CANDIDATE": 1,\n        "GROUP_REPACK": 2,\n        "KEEP_REVIEW": 3,\n        "KEEP": 4,\n        "ANCHOR_KEEP": 5,\n        "STATIC_REVIEW": 6,\n    }\n\n    decisions.sort(\n        key=lambda r: (\n            priority.get(r["decision"], 99),\n            -r["escape"],\n            -r["without_anchor"],\n            r["page"],\n            r["resource"],\n        )\n    )\n\n    with (OUTPUT_DIR / "resource_decisions.csv").open(\n        "w", newline="", encoding="utf-8-sig"\n    ) as f:\n        w = csv.writer(f, delimiter=";")\n        w.writerow([\n            "page",\n            "category",\n            "resource",\n            "texture_items",\n            "item_count",\n            "total_pixel_area",\n            "max_width",\n            "max_height",\n            "estimated_min_atlas",\n            "rooms_using_resource",\n            "rooms_with_anchor",\n            "rooms_without_anchor",\n            "escape_rooms_if_isolated",\n            "partial_no_anchor_rooms",\n            "anchor_couse_ratio",\n            "no_anchor_ratio",\n            "escape_ratio",\n            "decision",\n            "move_candidate",\n            "reason",\n            "clone_RGBA4444_MiB",\n            "clone_BC3_MiB",\n            "clone_BC1_MiB",\n        ])\n\n        for row in decisions:\n            size = row["min_atlas"]\n\n            w.writerow([\n                row["page"],\n                row["category"],\n                row["resource"],\n                ",".join(map(str, row["items"])),\n                row["item_count"],\n                row["total_area"],\n                row["max_w"],\n                row["max_h"],\n                size if size is not None else "PACK_FAIL_OR_OVER_2048",\n                row["rooms_using"],\n                row["with_anchor"],\n                row["without_anchor"],\n                row["escape"],\n                row["partial"],\n                f\'{row["anchor_ratio"]:.4f}\',\n                f\'{row["no_anchor_ratio"]:.4f}\',\n                f\'{row["escape_ratio"]:.4f}\',\n                row["decision"],\n                row["move_candidate"],\n                row["reason"],\n                f\'{atlas_vram_mib(size, "RGBA4444"):.3f}\' if size else "",\n                f\'{atlas_vram_mib(size, "BC3"):.3f}\' if size else "",\n                f\'{atlas_vram_mib(size, "BC1"):.3f}\' if size else "",\n            ])\n\n    # ---------------------------------------------------------------------\n    # Escape rooms: direct proof where one alternate resource page is enough.\n    # ---------------------------------------------------------------------\n\n    with (OUTPUT_DIR / "escape_rooms.csv").open(\n        "w", newline="", encoding="utf-8-sig"\n    ) as f:\n        w = csv.writer(f, delimiter=";")\n        w.writerow([\n            "page",\n            "category",\n            "resource",\n            "room",\n            "decision",\n            "room_items_on_original_page",\n            "anchor_items",\n        ])\n\n        for row in decisions:\n            for room_name in row["escape_room_names"]:\n                used = sorted(room_page_items[room_name][row["page"]])\n\n                w.writerow([\n                    row["page"],\n                    row["category"],\n                    row["resource"],\n                    room_name,\n                    row["decision"],\n                    ",".join(map(str, used)),\n                    ",".join(\n                        map(str, sorted(page_anchor_items[row["page"]]))\n                    ),\n                ])\n\n    # ---------------------------------------------------------------------\n    # No-anchor signatures:\n    # detects groups that repeatedly appear together and should be moved or\n    # duplicated as ONE alternate atlas rather than item by item.\n    # ---------------------------------------------------------------------\n\n    signatures = defaultdict(lambda: {"rooms": []})\n\n    for page_id in anchored_pages:\n        anchors = page_anchor_items[page_id]\n\n        for room_name, per_page in room_page_items.items():\n            used = per_page.get(page_id, set())\n\n            if not used or used & anchors:\n                continue\n\n            resources = set()\n\n            for item_id in used:\n                resources.update(item_resource_keys.get(item_id, set()))\n\n            item_sig = tuple(sorted(used))\n            resource_sig = tuple(\n                sorted(resource_label(r) for r in resources)\n            )\n\n            key = (page_id, item_sig, resource_sig)\n            signatures[key]["rooms"].append(room_name)\n\n    signature_rows = []\n\n    for (page_id, item_sig, resource_sig), info in signatures.items():\n        signature_rows.append({\n            "page": page_id,\n            "items": item_sig,\n            "resources": resource_sig,\n            "rooms": sorted(info["rooms"]),\n            "count": len(info["rooms"]),\n        })\n\n    signature_rows.sort(\n        key=lambda r: (-r["count"], r["page"], len(r["items"]))\n    )\n\n    with (OUTPUT_DIR / "no_anchor_room_signatures.csv").open(\n        "w", newline="", encoding="utf-8-sig"\n    ) as f:\n        w = csv.writer(f, delimiter=";")\n        w.writerow([\n            "page",\n            "room_count",\n            "texture_items",\n            "resources",\n            "rooms",\n            "interpretation",\n        ])\n\n        for row in signature_rows:\n            interpretation = (\n                "SINGLE_RESOURCE_ALT_ATLAS"\n                if len(row["resources"]) == 1\n                else "GROUP_ALT_ATLAS"\n            )\n\n            w.writerow([\n                row["page"],\n                row["count"],\n                ",".join(map(str, row["items"])),\n                " | ".join(row["resources"]),\n                " | ".join(row["rooms"]),\n                interpretation,\n            ])\n\n    # ---------------------------------------------------------------------\n    # Move candidates\n    # ---------------------------------------------------------------------\n\n    move_rows = [r for r in decisions if r["move_candidate"]]\n\n    with (OUTPUT_DIR / "move_candidates.csv").open(\n        "w", newline="", encoding="utf-8-sig"\n    ) as f:\n        w = csv.writer(f, delimiter=";")\n        w.writerow([\n            "page",\n            "category",\n            "resource",\n            "rooms_using",\n            "rooms_with_anchor",\n            "rooms_without_anchor",\n            "escape_rooms",\n            "estimated_min_atlas",\n            "note",\n        ])\n\n        for row in move_rows:\n            w.writerow([\n                row["page"],\n                row["category"],\n                row["resource"],\n                row["rooms_using"],\n                row["with_anchor"],\n                row["without_anchor"],\n                row["escape"],\n                row["min_atlas"],\n                (\n                    "MOVE pode ser mais simples que DUPLICATE; "\n                    "validar impacto nas poucas rooms que usam anchor."\n                ),\n            ])\n\n    # ---------------------------------------------------------------------\n    # Summary\n    # ---------------------------------------------------------------------\n\n    counts = defaultdict(int)\n    for row in decisions:\n        counts[row["decision"]] += 1\n\n    summary = OUTPUT_DIR / "summary_v3.txt"\n\n    lines = [\n        "DeltaruneVita - Texture Repack Analyzer v3",\n        "=" * 78,\n        "",\n        f"Rooms: {len(rooms)}",\n        f"Embedded textures: {len(pages)}",\n        f"Texture Page Items: {len(items)}",\n        f"Anchored pages: {len(anchored_pages)}",\n        "",\n        "DECISOES",\n        "-" * 78,\n        f"DUPLICATE_HIGH_VALUE: {counts[\'DUPLICATE_HIGH_VALUE\']}",\n        f"DUPLICATE_CANDIDATE:  {counts[\'DUPLICATE_CANDIDATE\']}",\n        f"GROUP_REPACK:         {counts[\'GROUP_REPACK\']}",\n        f"KEEP:                 {counts[\'KEEP\']}",\n        f"KEEP_REVIEW:          {counts[\'KEEP_REVIEW\']}",\n        f"ANCHOR_KEEP:           {counts[\'ANCHOR_KEEP\']}",\n        f"STATIC_REVIEW:         {counts[\'STATIC_REVIEW\']}",\n        f"MOVE candidates:       {len(move_rows)}",\n        "",\n        "ANCHOR PAGES",\n        "-" * 78,\n    ]\n\n    for row in sorted(\n        anchor_page_rows,\n        key=lambda x: -x["without_anchor_ratio"],\n    ):\n        lines.append(\n            f\'Page {row["page"]:>2} | \'\n            f\'page rooms={row["rooms_page"]:>3} | \'\n            f\'anchor rooms={row["rooms_anchor"]:>3} | \'\n            f\'without anchor={row["rooms_without_anchor"]:>3} \'\n            f\'({row["without_anchor_ratio"]*100:5.1f}%) | \'\n            f\'{" | ".join(row["anchor_resources"])[:58]}\'\n        )\n\n    lines += [\n        "",\n        "TOP DUPLICATE_HIGH_VALUE",\n        "-" * 78,\n    ]\n\n    top_dupes = [\n        r for r in decisions\n        if r["decision"] == "DUPLICATE_HIGH_VALUE"\n    ]\n\n    for row in top_dupes[:40]:\n        lines.append(\n            f\'Page {row["page"]:>2} | \'\n            f\'{row["category"]}:{row["resource"][:34]:34} | \'\n            f\'rooms={row["rooms_using"]:>3} | \'\n            f\'anchor={row["with_anchor"]:>3} | \'\n            f\'escape={row["escape"]:>3} \'\n            f\'({row["escape_ratio"]*100:5.1f}%) | \'\n            f\'atlas={row["min_atlas"]}\'\n        )\n\n    lines += [\n        "",\n        "INTERPRETACAO",\n        "-" * 78,\n        "DUPLICATE_HIGH_VALUE:",\n        "  manter recurso original + clone em atlas menor pode reduzir working set.",\n        "",\n        "DUPLICATE_CANDIDATE:",\n        "  ha ganho direto, mas menor; revisar manualmente.",\n        "",\n        "GROUP_REPACK:",\n        "  uma room usa o recurso sem anchor, mas tambem usa outros recursos da",\n        "  mesma Texture Page. Duplicar apenas um nao libera a pagina original.",\n        "",\n        "MOVE:",\n        "  recurso quase nunca acompanha o anchor. Pode ser melhor mover de vez",\n        "  para um atlas menor em vez de manter duas fontes fisicas.",\n        "",\n        "KEEP:",\n        "  recurso geralmente e usado junto com o anchor; separar tende a piorar.",\n        "",\n        "IMPORTANTE:",\n        "  esta analise continua estatica. Fonts/tilesets selecionados por GML",\n        "  dinamicamente podem nao aparecer como uso da room. Nao remover recursos",\n        "  automaticamente com base apenas neste relatorio.",\n        "",\n        "A v3 mede ESCAPE ROOM de forma conservadora:",\n        "  a room so conta como escape se, depois de retirar o recurso candidato,",\n        "  nenhum outro Texture Item daquela pagina continuar necessario.",\n    ]\n\n    summary.write_text("\\n".join(lines), encoding="utf-8")\n\n    return {\n        "rooms": len(rooms),\n        "pages": len(pages),\n        "items": len(items),\n        "anchors": len(anchored_pages),\n        "high_dupes": counts["DUPLICATE_HIGH_VALUE"],\n        "dupes": counts["DUPLICATE_CANDIDATE"],\n        "groups": counts["GROUP_REPACK"],\n        "moves": len(move_rows),\n    }\n\n\ndef main():\n    print("=" * 96)\n    print("DELTARUNEVITA - TEXTURE REPACK ANALYZER V3")\n    print("=" * 96)\n    print()\n\n    if not DATA_WIN.exists():\n        print("ERRO: data.win nao encontrado:")\n        print(DATA_WIN)\n        return 1\n\n    cli = find_cli()\n\n    if cli is None:\n        print("ERRO: UndertaleModCli.exe nao encontrado em:")\n        print(CLI_FOLDER)\n        return 2\n\n    csx, raw_json = write_csx()\n\n    try:\n        run_cli(cli, csx)\n    except Exception as exc:\n        print()\n        print("ERRO DURANTE EXTRACAO:")\n        print(exc)\n        print("Nenhuma alteracao foi feita no data.win.")\n        return 3\n\n    if not raw_json.exists():\n        print("ERRO: raw_texture_analysis_v3.json nao foi gerado.")\n        return 4\n\n    print()\n    print("Calculando KEEP / MOVE / DUPLICATE / GROUP...")\n    print()\n\n    try:\n        result = build_reports(raw_json)\n    except Exception as exc:\n        print("ERRO AO GERAR RELATORIOS:")\n        print(exc)\n        return 5\n\n    print("=" * 96)\n    print("ANALISE V3 CONCLUIDA")\n    print("=" * 96)\n    print(f\'Rooms:                         {result["rooms"]}\')\n    print(f\'Embedded textures:             {result["pages"]}\')\n    print(f\'Texture Page Items:            {result["items"]}\')\n    print(f\'Paginas com anchor:            {result["anchors"]}\')\n    print(f\'DUPLICATE_HIGH_VALUE:          {result["high_dupes"]}\')\n    print(f\'DUPLICATE_CANDIDATE:           {result["dupes"]}\')\n    print(f\'GROUP_REPACK:                  {result["groups"]}\')\n    print(f\'MOVE candidates:               {result["moves"]}\')\n    print()\n    print("Arquivos gerados em:")\n    print(OUTPUT_DIR)\n    print()\n    print("Me envie principalmente:")\n    print("  summary_v3.txt")\n    print("  anchor_pages.csv")\n    print("  resource_decisions.csv")\n    print("  no_anchor_room_signatures.csv")\n    print("  move_candidates.csv")\n    print()\n    print("Nenhuma alteracao foi feita no data.win.")\n    return 0\n\n\nif __name__ == "__main__":\n    sys.exit(main())\n'
V55_SOURCE = 'import csv\nimport json\nimport math\nimport sys\nfrom collections import defaultdict\nfrom pathlib import Path\n\n# =============================================================================\n# DeltaruneVita - Global Texture Repack Analyzer v5.3.1 Coalesced Safe\n#\n# OBJETIVO\n#   Reorganizar TODAS as texture pages do Chapter 2 visando:\n#\n#   1. Minimizar a quantidade de atlas carregados por Room.\n#   2. Evitar atlas 2048x2048 sempre que possivel.\n#   3. Permitir 2048x2048 somente quando um TPI indivisivel realmente exigir.\n#   4. Evitar o problema:\n#\n#        atlas original 2048\n#        + atlas novo menor\n#\n#      na mesma Room.\n#\n#   5. Buscar "replacement pages", nao "extra pages".\n#\n# IMPORTANTE\n#   - READ-ONLY.\n#   - NAO altera data.win.\n#   - NAO gera EmbeddedTextures reais.\n#   - Cada Texture Page Item (TPI) e indivisivel.\n#   - Nenhum TPI e cortado.\n#\n# ENTRADA\n#   vita_texture_analysis_v3/raw_texture_analysis_v3.json\n#\n# SAIDA\n#   vita_texture_analysis_v5_global/\n#\n# PRINCIPIO CENTRAL\n#\n#   Em vez de:\n#\n#      original_page + alternate_page\n#\n#   este analisador tenta:\n#\n#      replacement_page_1\n#      replacement_page_2\n#      ...\n#\n#   e considera a pagina original substituida por completo quando TODOS os TPIs\n#   dela forem realocados.\n#\n# =============================================================================\n\nBASE_DIR = Path(r"C:\\Users\\wolff\\Documents\\SDKVita\\DeltaruneVita\\data\\Teste")\n\nV3_DIR = BASE_DIR / "vita_texture_analysis_v3"\nRAW_JSON = V3_DIR / "raw_texture_analysis_v3.json"\n\nOUTPUT_DIR = BASE_DIR / "vita_texture_analysis_v5_5_hybrid_unknown_source_safe"\n\n# Preferred texture page sizes.\nATLAS_SIZES = [64, 128, 256, 512, 1024, 2048]\n\n# Default hard preference: do not use 2048 unless needed.\nPREFER_MAX_SIZE = 1024\n\n# 2 px transparent padding around every TPI.\nPADDING = 2\n\n# Clustering by static room affinity.\nJACCARD_THRESHOLD = 0.30\nMIN_SHARED_ROOMS = 2\n\n# Max resources per affinity cluster before packing.\nMAX_CLUSTER_RESOURCES = 64\n\n# A resource/page relationship above this can be considered "shared".\nSHARED_ROOM_COUNT = 20\n\n# 2048 anchor policy:\n# A companion can share a forced 2048 atlas only when every statically known\n# Room using that companion is also a Room that uses the anchor. This avoids\n# making unrelated Rooms load the forced 2048 page.\nANCHOR_COMPANION_STRICT_SUBSET = True\n\n# Resources with no statically known Rooms are NOT mixed into anchor pages.\nALLOW_UNKNOWN_ROOM_COMPANIONS = False\n\n# v5.4 density-aware policy.\n#\n# The v5.3.1 plan was VRAM-safe, but produced thousands of sparse 512x512\n# pages. v5.4 explicitly optimizes BOTH:\n#   - Room working-set VRAM\n#   - global atlas density / total canvas area / texture-page count\n#\n# Small TPIs are allowed to use 64/128/256 again. A later safe consolidation\n# pass can merge unrelated pages when the exact per-Room VRAM cost does not\n# increase.\nMIN_BALANCED_ATLAS_SIZE = 64\nPREFERRED_SHARED_ATLAS_SIZE = 256\n\n# Prefer 256 for genuinely small content instead of immediately promoting it\n# to 512. 128/64 remain available when they are materially denser.\nDENSITY_PREFERRED_SMALL_SIZE = 256\n\n# Candidate occupancy is raw TPI pixel area / atlas canvas area.\n# It is a heuristic only; the hard safety rule remains exact Room VRAM.\nDENSITY_TARGET_OCCUPANCY = 0.30\n\n# Run two greedy consolidation passes. In practice the first pass does most\n# of the work; the second can absorb bins exposed by the first.\nDENSITY_COMPACTION_PASSES = 2\n\n# v5.5:\n# TPIs sem Room estatica conhecida sao reagrupados pela Texture Page ORIGINAL.\n# Eles ja eram co-residentes nessa pagina no data.win original, portanto essa\n# e uma relacao muito mais conservadora do que misturar unknowns arbitrarios.\nHYBRID_UNKNOWN_BY_SOURCE_PAGE = True\n\n# v5.4 density-aware safe consolidation:\n#\n# Atlases may be merged even when their Room sets are unrelated, provided\n# EVERY affected statically-known Room satisfies:\n#\n#   after_cost(room) <= before_cost(room)\n#\n# This means two sparse 512 pages can safely become one 512 page: a Room that\n# used only one of them still pays exactly one 512 page, while a Room that used\n# both improves. If the combined content fits 256/128/64, the result is even\n# cheaper.\nENABLE_ZERO_COST_COALESCING = True\n\n# Unknown-room atlases may merge only when the new atlas is no larger than\n# BOTH input atlases. That remains safe even for unknown runtime usage.\nCOALESCE_UNKNOWN_ROOM_ATLASES = True\n\n# If item width/height exceeds this, it requires a 2048 atlas.\nLARGE_THRESHOLD = 1024\n\n# Formats for comparative VRAM estimation.\nFORMATS = {\n    "RGBA8888": 4.0,\n    "RGBA4444": 2.0,\n    "BC3": 1.0,\n    "BC1": 0.5,\n}\n\nEPSILON = 1e-9\n\n\n# =============================================================================\n# Helpers\n# =============================================================================\n\ndef read_json(path):\n    return json.loads(path.read_text(encoding="utf-8-sig"))\n\n\ndef resource_key(category, resource):\n    return (str(category), str(resource))\n\n\ndef resource_label(key):\n    return f"{key[0]}:{key[1]}"\n\n\ndef vram_mib(size, fmt):\n    return size * size * FORMATS[fmt] / (1024 * 1024)\n\n\ndef jaccard(a, b):\n    if not a and not b:\n        return 1.0\n\n    union = a | b\n\n    if not union:\n        return 0.0\n\n    return len(a & b) / len(union)\n\n\ndef smallest_atlas_for_item(width, height, padding):\n    """\n    Smallest atlas that can contain the TPI itself.\n\n    Padding is spacing BETWEEN packed TPIs, not a mandatory external border.\n    Therefore an exact 2048x1024 TPI is valid inside a 2048 atlas.\n    """\n    required_w = width\n    required_h = height\n\n    for size in ATLAS_SIZES:\n        if required_w <= size and required_h <= size:\n            return size\n\n    return None\n\n\n# =============================================================================\n# Packing\n# =============================================================================\n\ndef pack_rectangles(rectangles, atlas_size, padding):\n    """\n    Shelf first-fit-decreasing packing.\n\n    Every TPI is indivisible.\n\n    IMPORTANT:\n      `padding` is an inter-item gap, NOT a required outer border.\n      This allows exact-boundary items such as 2048x1024 inside 2048x2048.\n\n    Returns:\n      dict[item_id] = {x,y,width,height}\n    """\n\n    ordered = sorted(\n        rectangles,\n        key=lambda r: (\n            -r["height"],\n            -r["width"],\n            -(r["width"] * r["height"]),\n            r["id"],\n        ),\n    )\n\n    shelves = []\n    placements = {}\n\n    for rect in ordered:\n        w = rect["width"]\n        h = rect["height"]\n\n        if w > atlas_size or h > atlas_size:\n            raise RuntimeError(\n                f"TPI {rect[\'id\']} ({w}x{h}) nao cabe em {atlas_size}."\n            )\n\n        placed = False\n\n        # Existing shelves. Padding is required only when another item follows\n        # an already placed item horizontally.\n        for shelf in shelves:\n            x = shelf["x"]\n\n            if x > 0:\n                x += padding\n\n            if h <= shelf["height"] and x + w <= atlas_size:\n                placements[rect["id"]] = {\n                    "x": x,\n                    "y": shelf["y"],\n                    "width": w,\n                    "height": h,\n                }\n\n                shelf["x"] = x + w\n                placed = True\n                break\n\n        if placed:\n            continue\n\n        # New shelf. Padding is required only between shelves, never around\n        # the outside edge of the atlas.\n        if shelves:\n            new_y = shelves[-1]["y"] + shelves[-1]["height"] + padding\n        else:\n            new_y = 0\n\n        if new_y + h > atlas_size:\n            raise RuntimeError(\n                f"TPIs nao cabem em {atlas_size}x{atlas_size}."\n            )\n\n        shelves.append({\n            "y": new_y,\n            "height": h,\n            "x": w,\n        })\n\n        placements[rect["id"]] = {\n            "x": 0,\n            "y": new_y,\n            "width": w,\n            "height": h,\n        }\n\n    # Bounds / overlap sanity.\n    ids = list(placements)\n\n    for item_id, p in placements.items():\n        if (\n            p["x"] < 0\n            or p["y"] < 0\n            or p["x"] + p["width"] > atlas_size\n            or p["y"] + p["height"] > atlas_size\n        ):\n            raise RuntimeError(\n                f"Packing invalido para TPI {item_id}."\n            )\n\n    for i in range(len(ids)):\n        a = placements[ids[i]]\n\n        for j in range(i + 1, len(ids)):\n            b = placements[ids[j]]\n\n            overlap = not (\n                a["x"] + a["width"] <= b["x"]\n                or b["x"] + b["width"] <= a["x"]\n                or a["y"] + a["height"] <= b["y"]\n                or b["y"] + b["height"] <= a["y"]\n            )\n\n            if overlap:\n                raise RuntimeError(\n                    f"Overlap entre TPIs {ids[i]} e {ids[j]}."\n                )\n\n    return placements\n\n\nFAST_PACK_THRESHOLD = 256\n\ndef pack_subset_greedy(rectangles, atlas_size, padding):\n    """\n    Fast subset packer for very large clusters.\n\n    Uses the same shelf placement policy as pack_rectangles, but evaluates\n    each rectangle once for a candidate atlas instead of repeatedly\n    repacking selected+[item].\n    """\n    ordered = sorted(\n        rectangles,\n        key=lambda r: (\n            -r["height"],\n            -r["width"],\n            -(r["width"] * r["height"]),\n            r["id"],\n        ),\n    )\n\n    shelves = []\n    placements = {}\n    selected = []\n\n    for rect in ordered:\n        w = rect["width"]\n        h = rect["height"]\n\n        if w > atlas_size or h > atlas_size:\n            continue\n\n        placed = False\n\n        for shelf in shelves:\n            x = shelf["x"]\n            if x > 0:\n                x += padding\n\n            if h <= shelf["height"] and x + w <= atlas_size:\n                placements[rect["id"]] = {\n                    "x": x,\n                    "y": shelf["y"],\n                    "width": w,\n                    "height": h,\n                }\n                shelf["x"] = x + w\n                selected.append(rect)\n                placed = True\n                break\n\n        if placed:\n            continue\n\n        new_y = (\n            shelves[-1]["y"] + shelves[-1]["height"] + padding\n            if shelves else 0\n        )\n\n        if new_y + h <= atlas_size:\n            shelves.append({\n                "y": new_y,\n                "height": h,\n                "x": w,\n            })\n\n            placements[rect["id"]] = {\n                "x": 0,\n                "y": new_y,\n                "width": w,\n                "height": h,\n            }\n            selected.append(rect)\n\n    return selected, placements\n\n\ndef pack_cluster_into_multiple_atlases(\n    cluster_items,\n    preferred_max_size=PREFER_MAX_SIZE,\n    item_rooms_lookup=None,\n):\n    """\n    Packs a cluster into one or more atlases.\n\n    v5.2 rules:\n      1. 2048 is allowed only when at least one TPI actually requires it.\n      2. A forced 2048 atlas is an ANCHOR atlas.\n      3. Additional TPIs may share that 2048 atlas only when their known Room\n         set is fully contained in the anchor Room set.\n      4. TPIs with unknown/no static Rooms are never mixed into a forced 2048\n         anchor page.\n      5. Non-anchor resources prefer fewer 256/512/1024 atlases instead of\n         producing thousands of 128 pages.\n    """\n    if item_rooms_lookup is None:\n        item_rooms_lookup = {}\n\n    remaining = sorted(\n        cluster_items,\n        key=lambda x: (\n            -max(x["width"], x["height"]),\n            -(x["width"] * x["height"]),\n            x["id"],\n        ),\n    )\n\n    bins = []\n\n    # ---------------------------------------------------------------------\n    # Phase 1: forced 2048 anchors.\n    # ---------------------------------------------------------------------\n    forced_ids = {\n        item["id"]\n        for item in remaining\n        if smallest_atlas_for_item(\n            item["width"],\n            item["height"],\n            PADDING,\n        ) == 2048\n    }\n\n    while forced_ids:\n        anchor_id = min(\n            forced_ids,\n            key=lambda item_id: (\n                -next(\n                    x["width"] * x["height"]\n                    for x in remaining\n                    if x["id"] == item_id\n                ),\n                item_id,\n            ),\n        )\n\n        anchor = next(\n            x for x in remaining\n            if x["id"] == anchor_id\n        )\n\n        anchor_rooms = set(\n            item_rooms_lookup.get(anchor_id, set())\n        )\n\n        selected = [anchor]\n\n        # Only companions fully contained in anchor rooms.\n        candidates = []\n\n        for item in remaining:\n            if item["id"] == anchor_id:\n                continue\n\n            required = smallest_atlas_for_item(\n                item["width"],\n                item["height"],\n                PADDING,\n            )\n\n            if required is None or required == 2048:\n                continue\n\n            rooms = set(\n                item_rooms_lookup.get(item["id"], set())\n            )\n\n            if not rooms and not ALLOW_UNKNOWN_ROOM_COMPANIONS:\n                continue\n\n            if ANCHOR_COMPANION_STRICT_SUBSET:\n                compatible = bool(rooms) and rooms.issubset(anchor_rooms)\n            else:\n                compatible = bool(rooms) and bool(anchor_rooms) and (\n                    len(rooms & anchor_rooms) / len(rooms)\n                    >= 0.95\n                )\n\n            if not compatible:\n                continue\n\n            # Prefer companions with strongest anchor affinity, then large area.\n            affinity = (\n                len(rooms & anchor_rooms) / len(rooms)\n                if rooms else 0.0\n            )\n\n            candidates.append((\n                -affinity,\n                -(item["width"] * item["height"]),\n                item["id"],\n                item,\n            ))\n\n        candidates.sort()\n\n        for _, _, _, item in candidates:\n            trial = selected + [item]\n\n            try:\n                pack_rectangles(\n                    trial,\n                    2048,\n                    PADDING,\n                )\n                selected = trial\n            except RuntimeError:\n                pass\n\n        placements = pack_rectangles(\n            selected,\n            2048,\n            PADDING,\n        )\n\n        bins.append({\n            "size": 2048,\n            "items": selected,\n            "placements": placements,\n            "anchor_item": anchor_id,\n            "anchor_rooms": sorted(anchor_rooms),\n        })\n\n        selected_ids = {\n            item["id"]\n            for item in selected\n        }\n\n        remaining = [\n            item\n            for item in remaining\n            if item["id"] not in selected_ids\n        ]\n\n        forced_ids -= selected_ids\n\n    # ---------------------------------------------------------------------\n    # Phase 2: all remaining non-anchor items.\n    #\n    # v5.4: density-aware candidate selection.\n    #\n    # Instead of always trying 512 first, evaluate all valid sizes and choose\n    # the candidate that gives the best physical density while still packing\n    # many TPIs together. This directly avoids cases like an 11x8 TPI living\n    # alone in a 512x512 canvas.\n    # ---------------------------------------------------------------------\n    while remaining:\n        first = remaining[0]\n\n        min_required = smallest_atlas_for_item(\n            first["width"],\n            first["height"],\n            PADDING,\n        )\n\n        if min_required is None:\n            raise RuntimeError(\n                f"TPI {first[\'id\']} excede 2048 e nao pode ser repackeado."\n            )\n\n        if min_required == 2048:\n            raise RuntimeError(\n                f"TPI {first[\'id\']} deveria ter sido tratado como anchor 2048."\n            )\n\n        candidate_sizes = [\n            size\n            for size in ATLAS_SIZES\n            if min_required <= size <= preferred_max_size\n        ]\n\n        candidates = []\n\n        for size in candidate_sizes:\n            selected = []\n            placements = None\n\n            if len(remaining) >= FAST_PACK_THRESHOLD:\n                selected, placements = pack_subset_greedy(\n                    remaining,\n                    size,\n                    PADDING,\n                )\n            else:\n                for item in remaining:\n                    required = smallest_atlas_for_item(\n                        item["width"],\n                        item["height"],\n                        PADDING,\n                    )\n\n                    if required is None or required > size:\n                        continue\n\n                    trial = selected + [item]\n\n                    try:\n                        trial_placements = pack_rectangles(\n                            trial,\n                            size,\n                            PADDING,\n                        )\n                        selected = trial\n                        placements = trial_placements\n                    except RuntimeError:\n                        continue\n\n            if not selected:\n                continue\n\n            pixel_area = sum(\n                int(item["width"]) * int(item["height"])\n                for item in selected\n            )\n            canvas_area = size * size\n            occupancy = pixel_area / canvas_area\n\n            # A useful compromise:\n            #   1. prefer candidates reaching healthy occupancy;\n            #   2. then minimize canvas area per packed TPI;\n            #   3. then maximize occupancy;\n            #   4. then prefer the smaller atlas.\n            healthy = occupancy >= DENSITY_TARGET_OCCUPANCY\n            area_per_item = canvas_area / max(1, len(selected))\n\n            candidates.append({\n                "size": size,\n                "selected": selected,\n                "placements": placements,\n                "occupancy": occupancy,\n                "healthy": healthy,\n                "area_per_item": area_per_item,\n            })\n\n        if not candidates:\n            raise RuntimeError(\n                f"Nao foi possivel criar bin para TPI {first[\'id\']}."\n            )\n\n        healthy_candidates = [\n            c for c in candidates if c["healthy"]\n        ]\n\n        if healthy_candidates:\n            chosen_info = min(\n                healthy_candidates,\n                key=lambda c: (\n                    c["area_per_item"],\n                    -c["occupancy"],\n                    c["size"],\n                ),\n            )\n        else:\n            chosen_info = min(\n                candidates,\n                key=lambda c: (\n                    c["area_per_item"],\n                    -c["occupancy"],\n                    c["size"],\n                ),\n            )\n\n        size = chosen_info["size"]\n        selected = chosen_info["selected"]\n        placements = chosen_info["placements"]\n\n        bins.append({\n            "size": size,\n            "items": selected,\n            "placements": placements,\n            "anchor_item": None,\n            "anchor_rooms": [],\n        })\n\n        selected_ids = {\n            item["id"]\n            for item in selected\n        }\n\n        remaining = [\n            item\n            for item in remaining\n            if item["id"] not in selected_ids\n        ]\n\n    return bins\n\n\n# =============================================================================\n# v5.3 - Zero-cost atlas coalescing\n# =============================================================================\n\ndef _rooms_comparable(a_rooms, b_rooms):\n    """\n    Safe zero-cost relationship:\n      A == B\n      A subset B\n      B subset A\n    """\n    a = set(a_rooms)\n    b = set(b_rooms)\n\n    if not a or not b:\n        return False\n\n    return a == b or a.issubset(b) or b.issubset(a)\n\n\ndef _dominant_room_set(a_rooms, b_rooms):\n    a = set(a_rooms)\n    b = set(b_rooms)\n\n    if a.issuperset(b):\n        return a\n\n    if b.issuperset(a):\n        return b\n\n    # This should never happen after _rooms_comparable.\n    return a | b\n\n\ndef _atlas_flat_items(atlas):\n    result = []\n\n    for item in atlas["items"]:\n        result.append({\n            "id": int(item["item"]),\n            "width": int(item["width"]),\n            "height": int(item["height"]),\n            "source_page": int(item["source_page"]),\n            "resources": list(item.get("resources", [])),\n        })\n\n    return result\n\n\ndef _atlas_pixel_area(atlas):\n    return sum(\n        int(item["width"]) * int(item["height"])\n        for item in atlas.get("items", [])\n    )\n\n\ndef _atlas_occupancy(atlas):\n    size = int(atlas["size"])\n    if size <= 0:\n        return 0.0\n    return _atlas_pixel_area(atlas) / float(size * size)\n\n\ndef _smallest_pack_size(items, max_size=2048):\n    """\n    Return the smallest supported atlas that can pack all items.\n    """\n    if not items:\n        return 64, {}\n\n    required = max(\n        smallest_atlas_for_item(\n            int(item["width"]),\n            int(item["height"]),\n            PADDING,\n        ) or 4096\n        for item in items\n    )\n\n    for size in ATLAS_SIZES:\n        if size < required or size > max_size:\n            continue\n\n        try:\n            placements = pack_rectangles(\n                items,\n                size,\n                PADDING,\n            )\n            return size, placements\n        except RuntimeError:\n            continue\n\n    return None, None\n\n\ndef _try_merge_atlas_pair(a, b):\n    """\n    v5.4 exact density-aware merge.\n\n    Unlike v5.3.1, equal/subset Room sets are NOT required.\n\n    A merge is accepted when:\n      1. all TPIs physically fit a supported target atlas;\n      2. no gratuitous 2048 atlas is created;\n      3. every statically known affected Room has after <= before VRAM;\n      4. for unknown-room data, target size may not exceed either input size.\n\n    This safely allows:\n      sparse 512 + sparse 512 -> dense 512\n      sparse 512 + sparse 512 -> 256\n      sparse 256 + sparse 256 -> 128\n\n    even when the Room sets are unrelated.\n    """\n    a_rooms = set(a.get("rooms", []))\n    b_rooms = set(b.get("rooms", []))\n\n    size_a = int(a["size"])\n    size_b = int(b["size"])\n\n    items = _atlas_flat_items(a) + _atlas_flat_items(b)\n\n    # Defensive TPI dedupe.\n    unique = {}\n    for item in items:\n        unique[item["id"]] = item\n    items = list(unique.values())\n\n    # Never grow beyond the larger current page. Growing is not needed for\n    # density consolidation and makes the safety proof less useful.\n    max_target_size = max(size_a, size_b)\n\n    target_size, placements = _smallest_pack_size(\n        items,\n        max_size=max_target_size,\n    )\n\n    if target_size is None:\n        return None\n\n    forced_2048_items = [\n        item["id"]\n        for item in items\n        if smallest_atlas_for_item(\n            item["width"],\n            item["height"],\n            PADDING,\n        ) == 2048\n    ]\n\n    # 2048 is legal only if at least one atomic TPI requires it.\n    if target_size == 2048 and not forced_2048_items:\n        return None\n\n    affected_rooms = a_rooms | b_rooms\n\n    # Exact per-Room area-unit safety check.\n    for room in affected_rooms:\n        before_units = 0\n\n        if room in a_rooms:\n            before_units += size_a * size_a\n\n        if room in b_rooms:\n            before_units += size_b * size_b\n\n        after_units = target_size * target_size\n\n        if after_units > before_units:\n            return None\n\n    # v5.5: zero-room atlas families from different ORIGINAL source pages\n    # are never mixed. The hybrid pass already densely repacks each original\n    # page family before this generic consolidation stage.\n    if not a_rooms and not b_rooms:\n        source_a = a.get("hybrid_unknown_source_page")\n        source_b = b.get("hybrid_unknown_source_page")\n\n        if (\n            source_a is not None\n            and source_b is not None\n            and source_a != source_b\n        ):\n            return None\n\n    # Unknown/no-static-room pages are allowed only when the new page is no\n    # larger than each input page.\n    if not a_rooms or not b_rooms:\n        if not COALESCE_UNKNOWN_ROOM_ATLASES:\n            return None\n\n        if target_size > min(size_a, size_b):\n            return None\n\n    merged_rooms = sorted(affected_rooms)\n\n    merged_items = []\n    for item in sorted(items, key=lambda x: x["id"]):\n        p = placements[item["id"]]\n\n        merged_items.append({\n            "item": item["id"],\n            "source_page": item["source_page"],\n            "width": item["width"],\n            "height": item["height"],\n            "new_x": p["x"],\n            "new_y": p["y"],\n            "resources": item["resources"],\n        })\n\n    anchor_items = []\n\n    for atlas in (a, b):\n        if atlas.get("anchor_item") is not None:\n            anchor_items.append(int(atlas["anchor_item"]))\n\n        for x in atlas.get("anchor_items", []):\n            anchor_items.append(int(x))\n\n    anchor_items = sorted(set(anchor_items))\n\n    before_canvas = size_a * size_a + size_b * size_b\n    after_canvas = target_size * target_size\n\n    source_a = a.get("hybrid_unknown_source_page")\n    source_b = b.get("hybrid_unknown_source_page")\n\n    merged_unknown_source_page = (\n        source_a\n        if source_a is not None and source_a == source_b\n        else None\n    )\n\n    return {\n        "atlas_id": "",\n        "hybrid_unknown_source_page": merged_unknown_source_page,\n        "cluster_index": min(\n            int(a.get("cluster_index", 0)),\n            int(b.get("cluster_index", 0)),\n        ),\n        "size": target_size,\n        "forced_2048": bool(forced_2048_items),\n        "forced_2048_items": sorted(set(forced_2048_items)),\n        "anchor_item": anchor_items[0] if anchor_items else None,\n        "anchor_items": anchor_items,\n        "anchor_rooms": merged_rooms if target_size == 2048 else [],\n        "items": merged_items,\n        "rooms": merged_rooms,\n        "coalesced_from": sorted(\n            set(\n                [a["atlas_id"], b["atlas_id"]]\n                + list(a.get("coalesced_from", []))\n                + list(b.get("coalesced_from", []))\n            )\n        ),\n        "_merge_canvas_saved": before_canvas - after_canvas,\n        "_merge_occupancy": (\n            sum(i["width"] * i["height"] for i in items)\n            / float(after_canvas)\n        ),\n    }\n\n\ndef _merge_score(candidate, a, b):\n    """\n    Higher is better.\n\n    Primary goal is to remove canvas area (which strongly correlates with the\n    .win inflation observed in v0.71-alpha). Secondary goals are occupancy and\n    page-count reduction.\n    """\n    saved = int(candidate.get("_merge_canvas_saved", 0))\n    occupancy = float(candidate.get("_merge_occupancy", 0.0))\n\n    # Prefer actually shrinking canvas area. Same-size merges are still useful:\n    # they remove one EmbeddedTexture with zero Room VRAM regression.\n    return (\n        saved,\n        occupancy,\n        -int(candidate["size"]),\n        len(candidate.get("items", [])),\n    )\n\n\ndef _density_compaction_pass(working, history, pass_index):\n    """\n    Greedy best-fit pass.\n\n    Each source atlas is tested against already-built bins. This avoids the\n    O(N^3)-like behavior of repeatedly scanning every pair after every merge,\n    while still allowing a dense bin to absorb many sparse source pages.\n    """\n    ordered = sorted(\n        working,\n        key=lambda a: (\n            -int(a["size"]),\n            _atlas_occupancy(a),\n            len(a.get("rooms", [])),\n            a["atlas_id"],\n        ),\n    )\n\n    bins = []\n\n    total_ordered = len(ordered)\n\n    progress(\n        56.0 + (pass_index - 1) * 8.0,\n        f"Density pass {pass_index}: processando {total_ordered} atlas..."\n    )\n\n    for atlas_index, atlas in enumerate(ordered, 1):\n        best_index = None\n        best_candidate = None\n        best_score = None\n\n        for idx, existing in enumerate(bins):\n            candidate = _try_merge_atlas_pair(\n                existing,\n                atlas,\n            )\n\n            if candidate is None:\n                continue\n\n            score = _merge_score(\n                candidate,\n                existing,\n                atlas,\n            )\n\n            if best_score is None or score > best_score:\n                best_index = idx\n                best_candidate = candidate\n                best_score = score\n\n        if best_candidate is None:\n            bins.append(dict(atlas))\n            continue\n\n        old_a = bins[best_index]\n        old_b = atlas\n\n        best_candidate["atlas_id"] = (\n            f"DENS_P{pass_index}_"\n            f"{len(history)+1:05d}_"\n            f"{best_candidate[\'size\']}"\n        )\n\n        history.append({\n            "new_atlas": best_candidate["atlas_id"],\n            "size": best_candidate["size"],\n            "from_a": old_a["atlas_id"],\n            "from_b": old_b["atlas_id"],\n            "rooms": best_candidate["rooms"],\n            "item_count": len(best_candidate["items"]),\n            "anchor_items": best_candidate.get("anchor_items", []),\n            "before_canvas_pixels": (\n                int(old_a["size"]) ** 2\n                + int(old_b["size"]) ** 2\n            ),\n            "after_canvas_pixels": (\n                int(best_candidate["size"]) ** 2\n            ),\n            "canvas_saved_pixels": int(\n                best_candidate.get("_merge_canvas_saved", 0)\n            ),\n            "occupancy_after": float(\n                best_candidate.get("_merge_occupancy", 0.0)\n            ),\n            "pass": pass_index,\n        })\n\n        bins[best_index] = best_candidate\n\n        if (\n            atlas_index % 100 == 0\n            or atlas_index == total_ordered\n        ):\n            pass_base = 56.0 + (pass_index - 1) * 8.0\n            progress(\n                min(74.0, pass_base + 7.5 * atlas_index / max(1, total_ordered)),\n                f"Density pass {pass_index}: "\n                f"{atlas_index}/{total_ordered} | bins={len(bins)} | "\n                f"merges_total={len(history)}"\n            )\n\n    return bins\n\n\ndef coalesce_zero_cost_atlases(atlas_plan):\n    """\n    v5.4 density-aware safe consolidation.\n\n    The name is kept for compatibility with main(), but this is broader than\n    v5.3.1 coalescing: pages with unrelated Room sets may share one atlas when\n    exact Room VRAM never increases.\n\n    This directly targets the v0.71-alpha failure mode:\n      thousands of very sparse 512x512 EmbeddedTextures.\n    """\n    if not ENABLE_ZERO_COST_COALESCING:\n        return atlas_plan, []\n\n    working = [dict(atlas) for atlas in atlas_plan]\n    history = []\n\n    for pass_index in range(1, DENSITY_COMPACTION_PASSES + 1):\n        before_count = len(working)\n        before_area = sum(\n            int(a["size"]) ** 2\n            for a in working\n        )\n\n        working = _density_compaction_pass(\n            working,\n            history,\n            pass_index,\n        )\n\n        after_count = len(working)\n        after_area = sum(\n            int(a["size"]) ** 2\n            for a in working\n        )\n\n        progress(\n            min(74.5, 63.5 + pass_index * 5.0),\n            f"Density pass {pass_index} concluido: "\n            f"atlas {before_count} -> {after_count} | "\n            f"canvas {before_area:,} -> {after_area:,} px"\n        )\n\n        if (\n            after_count == before_count\n            and after_area == before_area\n        ):\n            break\n\n    # Remove internal heuristic fields.\n    for atlas in working:\n        atlas.pop("_merge_canvas_saved", None)\n        atlas.pop("_merge_occupancy", None)\n\n    # Deterministic final IDs.\n    working = sorted(\n        working,\n        key=lambda a: (\n            -int(a["size"]),\n            -len(a.get("rooms", [])),\n            min(\n                [int(x["item"]) for x in a["items"]]\n                or [999999]\n            ),\n        ),\n    )\n\n    for idx, atlas in enumerate(working, 1):\n        old = atlas["atlas_id"]\n        atlas["atlas_id"] = (\n            f"GLOBAL55_A{idx:04d}_{atlas[\'size\']}"\n        )\n\n        provenance = list(\n            atlas.get("coalesced_from", [])\n        )\n\n        if (\n            old.startswith("GLOBAL_")\n            or old.startswith("COAL_")\n            or old.startswith("DENS_")\n        ):\n            provenance.append(old)\n\n        atlas["coalesced_from"] = sorted(\n            set(provenance)\n        )\n\n    return working, history\n\n\n# =============================================================================\n# Progress / live logging\n# =============================================================================\n\ndef progress(percent, message):\n    percent = max(0.0, min(100.0, float(percent)))\n    print(\n        f"[{percent:6.2f}%] {message}",\n        flush=True,\n    )\n\n\n# =============================================================================\n# Main\n# =============================================================================\n\ndef main():\n    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)\n\n    progress(0.0, "Iniciando v5.5 Hybrid Unknown-Source Safe...")\n    progress(0.2, f"BASE_DIR: {BASE_DIR}")\n    progress(0.3, f"RAW_JSON: {RAW_JSON}")\n    progress(0.4, f"Saida: {OUTPUT_DIR}")\n\n    if not RAW_JSON.exists():\n        print(f"ERRO: raw v3 nao encontrado: {RAW_JSON}")\n        return 1\n\n    progress(0.5, "Carregando analise v3...")\n    raw = read_json(RAW_JSON)\n\n    pages = raw["pages"]\n    items = raw["items"]\n    rooms = raw["rooms"]\n\n    progress(\n        1.0,\n        f"Carregado: {len(items)} TPIs | "\n        f"{len(pages)} Texture Pages | "\n        f"{len(rooms)} Rooms"\n    )\n\n    item_by_id = {\n        int(item["item"]): item\n        for item in items\n    }\n\n    # -------------------------------------------------------------------------\n    # Resource / TPI / room maps\n    # -------------------------------------------------------------------------\n\n    resource_items = defaultdict(set)\n    item_resources = defaultdict(set)\n    resource_rooms = defaultdict(set)\n    item_rooms = defaultdict(set)\n    page_items = defaultdict(set)\n    page_rooms = defaultdict(set)\n\n    progress(2.0, "Mapeando Resource -> TPI -> Room...")\n\n    for item_index, item in enumerate(items, 1):\n        item_id = int(item["item"])\n        page_id = int(item["page"])\n\n        page_items[page_id].add(item_id)\n\n        for ref in item.get("resources", []):\n            key = resource_key(\n                ref.get("category", "OTHER"),\n                ref.get("resource", "?"),\n            )\n\n            resource_items[key].add(item_id)\n            item_resources[item_id].add(key)\n\n        if item_index % 1000 == 0 or item_index == len(items):\n            progress(\n                2.0 + 3.0 * item_index / max(1, len(items)),\n                f"Mapeando TPIs... {item_index}/{len(items)}"\n            )\n\n    for room_index, room in enumerate(rooms, 1):\n        room_name = room["room"]\n\n        for entry in room.get("page_items", []):\n            page_id = int(entry["page"])\n\n            used = {\n                int(x)\n                for x in entry.get("used_texture_items", [])\n            }\n\n            if used:\n                page_rooms[page_id].add(room_name)\n\n            for item_id in used:\n                item_rooms[item_id].add(room_name)\n\n                for key in item_resources.get(item_id, set()):\n                    resource_rooms[key].add(room_name)\n\n        if room_index % 25 == 0 or room_index == len(rooms):\n            progress(\n                5.0 + 3.0 * room_index / max(1, len(rooms)),\n                f"Mapeando Rooms... {room_index}/{len(rooms)}"\n            )\n\n    # -------------------------------------------------------------------------\n    # Convert TPIs to global atomic units.\n    #\n    # Prefer resource-level grouping when possible; unreferenced TPIs become\n    # their own pseudo-resource so every TPI is accounted for.\n    # -------------------------------------------------------------------------\n\n    progress(8.0, "Criando unidades atomicas de recursos/TPIs...")\n\n    unit_items = defaultdict(set)\n    unit_rooms = defaultdict(set)\n    unit_category = {}\n\n    unknown_tpi_count = 0\n    unknown_source_pages = set()\n\n    for item in items:\n        item_id = int(item["item"])\n        refs = sorted(item_resources.get(item_id, set()))\n        known_rooms = set(item_rooms.get(item_id, set()))\n        source_page = int(item["page"])\n\n        if HYBRID_UNKNOWN_BY_SOURCE_PAGE and not known_rooms:\n            key = (\n                "UNKNOWN_SOURCE_PAGE",\n                f"PAGE_{source_page:04d}",\n            )\n            unit_items[key].add(item_id)\n            unit_category[key] = "UNKNOWN_SOURCE_PAGE"\n            unknown_tpi_count += 1\n            unknown_source_pages.add(source_page)\n            continue\n\n        if refs:\n            for key in refs:\n                unit_items[key].add(item_id)\n                unit_rooms[key].update(known_rooms)\n                unit_category[key] = key[0]\n        else:\n            key = ("UNREFERENCED", f"TPI_{item_id}")\n            unit_items[key].add(item_id)\n            unit_rooms[key].update(known_rooms)\n            unit_category[key] = "UNREFERENCED"\n\n    progress(\n        10.0,\n        f"TPIs sem Room conhecida: {unknown_tpi_count} | "\n        f"source pages originais: {len(unknown_source_pages)}"\n    )\n\n    units = []\n\n    for key, tpis in unit_items.items():\n        dims = [\n            (\n                int(item_by_id[item_id]["width"]),\n                int(item_by_id[item_id]["height"]),\n            )\n            for item_id in tpis\n        ]\n\n        min_required = max(\n            smallest_atlas_for_item(w, h, PADDING) or 4096\n            for w, h in dims\n        )\n\n        source_pages_for_unit = sorted({\n            int(item_by_id[item_id]["page"])\n            for item_id in tpis\n        })\n\n        units.append({\n            "key": key,\n            "label": resource_label(key),\n            "items": sorted(tpis),\n            "rooms": set(unit_rooms.get(key, set())),\n            "category": unit_category.get(key, "OTHER"),\n            "min_required": min_required,\n            "source_pages": source_pages_for_unit,\n            "is_unknown_source_unit": (\n                unit_category.get(key) == "UNKNOWN_SOURCE_PAGE"\n            ),\n        })\n\n    progress(\n        12.0,\n        f"Unidades atomicas criadas: {len(units)}"\n    )\n\n    # -------------------------------------------------------------------------\n    # Build affinity clusters.\n    #\n    # Start each unit alone, then merge when room co-use is sufficiently high.\n    # Large units that force 2048 remain cluster anchors.\n    # -------------------------------------------------------------------------\n\n    clusters = []\n\n    # Seed with large first, then shared, then local.\n    units_sorted = sorted(\n        units,\n        key=lambda u: (\n            -(1 if u["min_required"] == 2048 else 0),\n            -len(u["rooms"]),\n            -len(u["items"]),\n            u["label"],\n        ),\n    )\n\n    progress(\n        13.0,\n        f"Calculando afinidade e clusters para {len(units_sorted)} unidades..."\n    )\n\n    for unit_index, unit in enumerate(units_sorted, 1):\n        best_index = None\n        best_score = -1.0\n\n        if unit.get("is_unknown_source_unit"):\n            clusters.append({\n                "units": [unit],\n                "rooms": set(),\n                "hybrid_unknown_source_page": (\n                    unit["source_pages"][0]\n                    if len(unit["source_pages"]) == 1\n                    else None\n                ),\n            })\n\n            if unit_index % 250 == 0 or unit_index == len(units_sorted):\n                progress(\n                    13.0 + 17.0 * unit_index / max(1, len(units_sorted)),\n                    f"Clustering... {unit_index}/{len(units_sorted)} | "\n                    f"clusters={len(clusters)}"\n                )\n            continue\n\n        for idx, cluster in enumerate(clusters):\n            if cluster.get("hybrid_unknown_source_page") is not None:\n                continue\n\n            if len(cluster["units"]) >= MAX_CLUSTER_RESOURCES:\n                continue\n\n            # Do not mix unrelated resources into a 2048 cluster unless they\n            # have strong room affinity.\n            score = jaccard(\n                unit["rooms"],\n                cluster["rooms"],\n            )\n\n            shared = len(\n                unit["rooms"]\n                & cluster["rooms"]\n            )\n\n            if (\n                score >= JACCARD_THRESHOLD\n                and shared >= MIN_SHARED_ROOMS\n                and score > best_score\n            ):\n                best_index = idx\n                best_score = score\n\n        if best_index is None:\n            clusters.append({\n                "units": [unit],\n                "rooms": set(unit["rooms"]),\n            })\n        else:\n            cluster = clusters[best_index]\n            cluster["units"].append(unit)\n            cluster["rooms"].update(unit["rooms"])\n\n        if unit_index % 250 == 0 or unit_index == len(units_sorted):\n            progress(\n                13.0 + 17.0 * unit_index / max(1, len(units_sorted)),\n                f"Clustering... {unit_index}/{len(units_sorted)} | "\n                f"clusters={len(clusters)}"\n            )\n\n    progress(\n        30.0,\n        f"Clustering concluido: {len(clusters)} clusters"\n    )\n\n    # -------------------------------------------------------------------------\n    # Pack clusters into replacement atlas bins.\n    # -------------------------------------------------------------------------\n\n    atlas_plan = []\n    item_target_atlas = {}\n\n    atlas_counter = 0\n\n    progress(\n        31.0,\n        f"Empacotando {len(clusters)} clusters..."\n    )\n\n    for cluster_index, cluster in enumerate(clusters, 1):\n        cluster_items = []\n        seen_items = set()\n\n        for unit in cluster["units"]:\n            for item_id in unit["items"]:\n                if item_id in seen_items:\n                    continue\n\n                seen_items.add(item_id)\n\n                item = item_by_id[item_id]\n\n                cluster_items.append({\n                    "id": item_id,\n                    "width": int(item["width"]),\n                    "height": int(item["height"]),\n                    "source_page": int(item["page"]),\n                    "resources": [\n                        resource_label(key)\n                        for key in sorted(\n                            item_resources.get(item_id, set())\n                        )\n                    ],\n                })\n\n        if len(cluster_items) >= FAST_PACK_THRESHOLD:\n            progress(\n                31.0 + 24.0 * (cluster_index - 1) / max(1, len(clusters)),\n                f"Packing cluster grande {cluster_index}/{len(clusters)} | "\n                f"items={len(cluster_items)} | "\n                f"source_page={cluster.get(\'hybrid_unknown_source_page\')}"\n            )\n\n        bins = pack_cluster_into_multiple_atlases(\n            cluster_items,\n            preferred_max_size=PREFER_MAX_SIZE,\n            item_rooms_lookup=item_rooms,\n        )\n\n        for local_index, bin_info in enumerate(bins, 1):\n            atlas_counter += 1\n\n            size = bin_info["size"]\n\n            atlas_id = (\n                f"GLOBAL_C{cluster_index:04d}_"\n                f"A{local_index:02d}_"\n                f"{size}"\n            )\n\n            forced_2048_items = [\n                item["id"]\n                for item in bin_info["items"]\n                if smallest_atlas_for_item(\n                    item["width"],\n                    item["height"],\n                    PADDING,\n                ) == 2048\n            ]\n\n            atlas_rooms = set()\n\n            for item in bin_info["items"]:\n                atlas_rooms.update(\n                    item_rooms.get(\n                        item["id"],\n                        set(),\n                    )\n                )\n\n            atlas_record = {\n                "atlas_id": atlas_id,\n                "cluster_index": cluster_index,\n                "size": size,\n                "forced_2048": bool(forced_2048_items),\n                "forced_2048_items": forced_2048_items,\n                "anchor_item": bin_info.get("anchor_item"),\n                "anchor_rooms": bin_info.get("anchor_rooms", []),\n                "items": [],\n                "rooms": sorted(atlas_rooms),\n                "hybrid_unknown_source_page": cluster.get(\n                    "hybrid_unknown_source_page"\n                ),\n            }\n\n            for item in sorted(\n                bin_info["items"],\n                key=lambda x: x["id"],\n            ):\n                p = bin_info["placements"][item["id"]]\n\n                atlas_record["items"].append({\n                    "item": item["id"],\n                    "source_page": item["source_page"],\n                    "width": item["width"],\n                    "height": item["height"],\n                    "new_x": p["x"],\n                    "new_y": p["y"],\n                    "resources": item["resources"],\n                })\n\n                item_target_atlas[item["id"]] = atlas_id\n\n            atlas_plan.append(atlas_record)\n\n        if (\n            cluster_index % 25 == 0\n            or cluster_index == len(clusters)\n        ):\n            progress(\n                31.0 + 24.0 * cluster_index / max(1, len(clusters)),\n                f"Packing... cluster {cluster_index}/{len(clusters)} | "\n                f"atlas={len(atlas_plan)}"\n            )\n\n    progress(\n        55.0,\n        f"Packing inicial concluido: {len(atlas_plan)} atlas"\n    )\n\n    # -------------------------------------------------------------------------\n    # v5.5: hybrid density-aware safe consolidation.\n    #\n    # This can merge:\n    #   - multiple 2048 anchors used by the same/subset Rooms;\n    #   - smaller atlases with equal/subset Room sets;\n    #\n    # without increasing the target atlas size.\n    # -------------------------------------------------------------------------\n\n    pre_coalesce_count = len(atlas_plan)\n\n    progress(\n        56.0,\n        f"Iniciando consolidacao density-aware de {pre_coalesce_count} atlas..."\n    )\n\n    atlas_plan, coalesce_history = coalesce_zero_cost_atlases(\n        atlas_plan\n    )\n\n    post_coalesce_count = len(atlas_plan)\n\n    progress(\n        75.0,\n        f"Consolidacao concluida: "\n        f"{pre_coalesce_count} -> {post_coalesce_count} atlas | "\n        f"merges={len(coalesce_history)}"\n    )\n\n    # Rebuild item -> target mapping after merges/renames.\n    item_target_atlas = {}\n\n    for atlas in atlas_plan:\n        for item in atlas["items"]:\n            item_target_atlas[int(item["item"])] = atlas["atlas_id"]\n\n    # -------------------------------------------------------------------------\n    # Validate every TPI is assigned exactly once.\n    # -------------------------------------------------------------------------\n\n    all_item_ids = {\n        int(item["item"])\n        for item in items\n    }\n\n    assigned_ids = set(item_target_atlas)\n\n    missing_items = sorted(\n        all_item_ids - assigned_ids\n    )\n\n    if missing_items:\n        raise RuntimeError(\n            f"{len(missing_items)} TPIs ficaram sem target atlas."\n        )\n\n    # -------------------------------------------------------------------------\n    # Simulate room working set under GLOBAL REPLACEMENT.\n    #\n    # Important difference from v4:\n    #   Original pages are not kept just because they existed.\n    #   A Room\'s after-set is derived ONLY from the target atlas of each used TPI.\n    # -------------------------------------------------------------------------\n\n    progress(78.0, "Simulando working-set VRAM Room por Room...")\n\n    room_results = []\n\n    for room_index, room in enumerate(rooms, 1):\n        room_name = room["room"]\n\n        original_pages = {\n            int(entry["page"])\n            for entry in room.get("page_items", [])\n            if entry.get("used_texture_items")\n        }\n\n        used_items = set()\n\n        for entry in room.get("page_items", []):\n            used_items.update(\n                int(x)\n                for x in entry.get("used_texture_items", [])\n            )\n\n        target_atlases = {\n            item_target_atlas[item_id]\n            for item_id in used_items\n            if item_id in item_target_atlas\n        }\n\n        atlas_size_by_id = {\n            atlas["atlas_id"]: atlas["size"]\n            for atlas in atlas_plan\n        }\n\n        before = {}\n        after = {}\n\n        for fmt in FORMATS:\n            b = 0.0\n            a = 0.0\n\n            # Original pages assumed 2048-ish based on v3 extent.\n            for page_id in original_pages:\n                page = next(\n                    p\n                    for p in pages\n                    if int(p["page"]) == page_id\n                )\n\n                max_extent = max(\n                    int(page.get("estimated_width", 1)),\n                    int(page.get("estimated_height", 1)),\n                )\n\n                original_size = 2048 if max_extent > 1024 else 1024\n\n                b += vram_mib(original_size, fmt)\n\n            for atlas_id in target_atlases:\n                a += vram_mib(\n                    atlas_size_by_id[atlas_id],\n                    fmt,\n                )\n\n            before[fmt] = b\n            after[fmt] = a\n\n        room_results.append({\n            "room": room_name,\n            "original_pages": sorted(original_pages),\n            "new_atlases": sorted(target_atlases),\n            "original_atlas_count": len(original_pages),\n            "new_atlas_count": len(target_atlases),\n            "before": before,\n            "after": after,\n            "delta_rgba4444": (\n                after["RGBA4444"]\n                - before["RGBA4444"]\n            ),\n        })\n\n    # -------------------------------------------------------------------------\n    # Metrics\n    # -------------------------------------------------------------------------\n\n    improved = [\n        r\n        for r in room_results\n        if r["delta_rgba4444"] < -EPSILON\n    ]\n\n    worse = [\n        r\n        for r in room_results\n        if r["delta_rgba4444"] > EPSILON\n    ]\n\n    equal = [\n        r\n        for r in room_results\n        if abs(r["delta_rgba4444"]) <= EPSILON\n    ]\n\n    # HARD SAFETY GATE:\n    # v5.5 must never accept a final plan with any Room worse in VRAM.\n    if worse:\n        worst = sorted(\n            worse,\n            key=lambda r: r["delta_rgba4444"],\n            reverse=True,\n        )[:20]\n\n        details = "\\n".join(\n            f"  {r[\'room\']}: "\n            f"{r[\'before\'][\'RGBA4444\']:.3f} -> "\n            f"{r[\'after\'][\'RGBA4444\']:.3f} MiB"\n            for r in worst\n        )\n\n        raise RuntimeError(\n            "SAFETY GATE: o coalescing gerou Rooms piores em VRAM.\\n"\n            + details\n        )\n\n    peak_before = max(\n        r["before"]["RGBA4444"]\n        for r in room_results\n    )\n\n    peak_after = max(\n        r["after"]["RGBA4444"]\n        for r in room_results\n    )\n\n    total_before = sum(\n        r["before"]["RGBA4444"]\n        for r in room_results\n    )\n\n    total_after = sum(\n        r["after"]["RGBA4444"]\n        for r in room_results\n    )\n\n    original_total_pages = len(pages)\n    new_total_pages = len(atlas_plan)\n\n    rooms_fewer_atlases = sum(\n        1 for r in room_results\n        if r["new_atlas_count"] < r["original_atlas_count"]\n    )\n    rooms_same_atlases = sum(\n        1 for r in room_results\n        if r["new_atlas_count"] == r["original_atlas_count"]\n    )\n    rooms_more_atlases = sum(\n        1 for r in room_results\n        if r["new_atlas_count"] > r["original_atlas_count"]\n    )\n\n    avg_original_atlases = (\n        sum(r["original_atlas_count"] for r in room_results)\n        / len(room_results)\n        if room_results else 0.0\n    )\n\n    avg_new_atlases = (\n        sum(r["new_atlas_count"] for r in room_results)\n        / len(room_results)\n        if room_results else 0.0\n    )\n\n    original_2048_pages = sum(\n        1\n        for p in pages\n        if max(\n            int(p.get("estimated_width", 1)),\n            int(p.get("estimated_height", 1)),\n        ) > 1024\n    )\n\n    new_2048_pages = sum(\n        1\n        for a in atlas_plan\n        if a["size"] == 2048\n    )\n\n    gratuitous_2048 = [\n        a\n        for a in atlas_plan\n        if (\n            a["size"] == 2048\n            and not a["forced_2048"]\n        )\n    ]\n\n    # -------------------------------------------------------------------------\n    # Outputs\n    # -------------------------------------------------------------------------\n\n    # coalesce_history.csv\n    with (OUTPUT_DIR / "coalesce_history.csv").open(\n        "w",\n        newline="",\n        encoding="utf-8-sig",\n    ) as f:\n        w = csv.writer(f, delimiter=";")\n\n        w.writerow([\n            "new_atlas",\n            "size",\n            "from_a",\n            "from_b",\n            "room_count",\n            "item_count",\n            "anchor_items",\n            "before_canvas_pixels",\n            "after_canvas_pixels",\n            "canvas_saved_pixels",\n            "occupancy_after",\n            "pass",\n            "rooms",\n        ])\n\n        for row in coalesce_history:\n            w.writerow([\n                row["new_atlas"],\n                row["size"],\n                row["from_a"],\n                row["from_b"],\n                len(row["rooms"]),\n                row["item_count"],\n                ",".join(map(str, row["anchor_items"])),\n                row.get("before_canvas_pixels", ""),\n                row.get("after_canvas_pixels", ""),\n                row.get("canvas_saved_pixels", ""),\n                (\n                    f\'{row.get("occupancy_after", 0.0):.6f}\'\n                    if row.get("occupancy_after") is not None\n                    else ""\n                ),\n                row.get("pass", ""),\n                " | ".join(row["rooms"]),\n            ])\n\n    # global_atlas_plan.csv\n    with (OUTPUT_DIR / "global_atlas_plan.csv").open(\n        "w",\n        newline="",\n        encoding="utf-8-sig",\n    ) as f:\n        w = csv.writer(f, delimiter=";")\n\n        w.writerow([\n            "atlas_id",\n            "size",\n            "forced_2048",\n            "forced_2048_items",\n            "anchor_item",\n            "anchor_items",\n            "coalesced_from",\n            "anchor_room_count",\n            "anchor_rooms",\n            "item_count",\n            "room_count",\n            "rooms",\n            "hybrid_unknown_source_page",\n        ])\n\n        for atlas in atlas_plan:\n            w.writerow([\n                atlas["atlas_id"],\n                atlas["size"],\n                atlas["forced_2048"],\n                ",".join(\n                    map(str, atlas["forced_2048_items"])\n                ),\n                atlas.get("anchor_item") or "",\n                ",".join(map(str, atlas.get("anchor_items", []))),\n                " | ".join(atlas.get("coalesced_from", [])),\n                len(atlas.get("anchor_rooms", [])),\n                " | ".join(atlas.get("anchor_rooms", [])),\n                len(atlas["items"]),\n                len(atlas["rooms"]),\n                " | ".join(atlas["rooms"]),\n                atlas.get("hybrid_unknown_source_page", ""),\n            ])\n\n    # global_item_manifest.csv\n    with (OUTPUT_DIR / "global_item_manifest.csv").open(\n        "w",\n        newline="",\n        encoding="utf-8-sig",\n    ) as f:\n        w = csv.writer(f, delimiter=";")\n\n        w.writerow([\n            "texture_item",\n            "source_page",\n            "width",\n            "height",\n            "target_atlas",\n            "target_size",\n            "new_x",\n            "new_y",\n            "resources",\n        ])\n\n        atlas_lookup = {\n            a["atlas_id"]: a\n            for a in atlas_plan\n        }\n\n        for atlas in atlas_plan:\n            for item in atlas["items"]:\n                w.writerow([\n                    item["item"],\n                    item["source_page"],\n                    item["width"],\n                    item["height"],\n                    atlas["atlas_id"],\n                    atlas["size"],\n                    item["new_x"],\n                    item["new_y"],\n                    " | ".join(item["resources"]),\n                ])\n\n    # room comparison\n    with (OUTPUT_DIR / "room_global_before_after.csv").open(\n        "w",\n        newline="",\n        encoding="utf-8-sig",\n    ) as f:\n        w = csv.writer(f, delimiter=";")\n\n        w.writerow([\n            "room",\n            "original_atlas_count",\n            "new_atlas_count",\n            "atlas_count_delta",\n            "before_RGBA4444_MiB",\n            "after_RGBA4444_MiB",\n            "saving_RGBA4444_MiB",\n            "original_pages",\n            "new_atlases",\n        ])\n\n        for row in sorted(\n            room_results,\n            key=lambda r: (\n                r["before"]["RGBA4444"]\n                - r["after"]["RGBA4444"]\n            ),\n            reverse=True,\n        ):\n            w.writerow([\n                row["room"],\n                row["original_atlas_count"],\n                row["new_atlas_count"],\n                row["new_atlas_count"] - row["original_atlas_count"],\n                f\'{row["before"]["RGBA4444"]:.3f}\',\n                f\'{row["after"]["RGBA4444"]:.3f}\',\n                f\'{row["before"]["RGBA4444"] - row["after"]["RGBA4444"]:.3f}\',\n                ",".join(map(str, row["original_pages"])),\n                " | ".join(row["new_atlases"]),\n            ])\n\n    # Atlas size distribution\n    size_distribution = defaultdict(int)\n\n    for atlas in atlas_plan:\n        size_distribution[atlas["size"]] += 1\n\n    with (OUTPUT_DIR / "atlas_size_distribution.csv").open(\n        "w",\n        newline="",\n        encoding="utf-8-sig",\n    ) as f:\n        w = csv.writer(f, delimiter=";")\n        w.writerow(["size", "count"])\n\n        for size in ATLAS_SIZES:\n            w.writerow([\n                size,\n                size_distribution.get(size, 0),\n            ])\n\n    progress(86.0, "Calculando densidade fisica e area total de canvas...")\n\n    # Density / physical canvas metrics.\n    # These values must be computed BEFORE global_repack_plan.json is written.\n    total_canvas_pixels = sum(\n        int(a["size"]) * int(a["size"])\n        for a in atlas_plan\n    )\n\n    total_tpi_pixels = sum(\n        int(item["width"]) * int(item["height"])\n        for item in items\n    )\n\n    global_canvas_occupancy = (\n        total_tpi_pixels / total_canvas_pixels\n        if total_canvas_pixels\n        else 0.0\n    )\n\n    # Raw uncompressed equivalents. Actual PNG/.win size varies, but canvas\n    # area is the key pressure signal seen in v0.71-alpha.\n    canvas_rgba8888_mib = (\n        total_canvas_pixels * 4.0\n        / (1024 * 1024)\n    )\n    canvas_rgba4444_mib = (\n        total_canvas_pixels * 2.0\n        / (1024 * 1024)\n    )\n\n    unknown_final_atlases = [\n        a for a in atlas_plan\n        if not a.get("rooms", [])\n    ]\n    known_final_atlases = [\n        a for a in atlas_plan\n        if a.get("rooms", [])\n    ]\n    single_tpi_atlases = [\n        a for a in atlas_plan\n        if len(a.get("items", [])) == 1\n    ]\n    hybrid_unknown_atlases = [\n        a for a in atlas_plan\n        if a.get("hybrid_unknown_source_page") is not None\n    ]\n    unknown_final_canvas_pixels = sum(\n        int(a["size"]) ** 2\n        for a in unknown_final_atlases\n    )\n\n    progress(\n        87.0,\n        f"Hybrid: unknown atlas={len(unknown_final_atlases)} | "\n        f"single-TPI={len(single_tpi_atlases)}"\n    )\n\n    # Full JSON\n    (OUTPUT_DIR / "global_repack_plan.json").write_text(\n        json.dumps(\n            {\n                "atlas_sizes": ATLAS_SIZES,\n                "preferred_max_size": PREFER_MAX_SIZE,\n                "padding": PADDING,\n                "version": "5.5-hybrid-unknown-source-safe",\n                "density_target_occupancy": DENSITY_TARGET_OCCUPANCY,\n                "density_compaction_passes": DENSITY_COMPACTION_PASSES,\n                "hybrid_unknown_by_source_page": HYBRID_UNKNOWN_BY_SOURCE_PAGE,\n                "unknown_tpi_count": unknown_tpi_count,\n                "unknown_source_pages": sorted(unknown_source_pages),\n                "final_unknown_atlas_count": len(unknown_final_atlases),\n                "final_known_atlas_count": len(known_final_atlases),\n                "final_single_tpi_atlas_count": len(single_tpi_atlases),\n                "total_canvas_pixels": total_canvas_pixels,\n                "total_tpi_pixels": total_tpi_pixels,\n                "global_canvas_occupancy": global_canvas_occupancy,\n                "atlas_plan": atlas_plan,\n                "coalesce_history": coalesce_history,\n                "room_results": room_results,\n            },\n            ensure_ascii=False,\n            indent=2,\n        ),\n        encoding="utf-8",\n    )\n\n    progress(88.0, "Gerando relatorios finais...")\n\n    density_rows = []\n\n    for atlas in atlas_plan:\n        pixel_area = _atlas_pixel_area(atlas)\n        canvas_area = int(atlas["size"]) ** 2\n\n        density_rows.append({\n            "atlas_id": atlas["atlas_id"],\n            "size": int(atlas["size"]),\n            "item_count": len(atlas["items"]),\n            "tpi_pixel_area": pixel_area,\n            "canvas_pixel_area": canvas_area,\n            "occupancy": (\n                pixel_area / canvas_area\n                if canvas_area else 0.0\n            ),\n            "room_count": len(atlas.get("rooms", [])),\n        })\n\n    with (OUTPUT_DIR / "atlas_density.csv").open(\n        "w",\n        newline="",\n        encoding="utf-8-sig",\n    ) as f:\n        w = csv.writer(f, delimiter=";")\n        w.writerow([\n            "atlas_id",\n            "size",\n            "item_count",\n            "room_count",\n            "tpi_pixel_area",\n            "canvas_pixel_area",\n            "occupancy_percent",\n        ])\n\n        for row in sorted(\n            density_rows,\n            key=lambda x: (\n                x["occupancy"],\n                -x["size"],\n                x["atlas_id"],\n            ),\n        ):\n            w.writerow([\n                row["atlas_id"],\n                row["size"],\n                row["item_count"],\n                row["room_count"],\n                row["tpi_pixel_area"],\n                row["canvas_pixel_area"],\n                f\'{row["occupancy"] * 100.0:.3f}\',\n            ])\n\n    # Summary\n    lines = [\n        "DeltaruneVita - Global Texture Repack Analyzer v5.5 Hybrid Unknown-Source Safe + Live Progress",\n        "=" * 96,\n        "",\n        "OBJETIVO",\n        "  Substituir globalmente as texture pages originais por atlas menores,",\n        "  evitando carregar 2048x2048 + atlas adicionais na mesma Room.",\n        "",\n        "REGRAS",\n        "  - TPI indivisivel.",\n        "  - Nenhum TPI e cortado.",\n        "  - 2048 somente quando um TPI individual exige.\\n  - Atlas 2048 recebe somente companions cujas Rooms conhecidas estao contidas nas Rooms do anchor.",\n        "  - Working set depois = apenas atlas novos usados pelos TPIs da Room.",\n        "  - 64/128/256 sao permitidos para evitar canvas 512 subutilizado.",\n        "  - TPIs sem Room conhecida sao reagrupados pela Texture Page ORIGINAL.",\n        "  - Unknowns de source pages diferentes nao sao misturados.",\n        "  - Atlas de Rooms conhecidas podem compartilhar pagina quando o custo exato por Room nao aumenta.",\n        "  - Cada merge e validado por Room: VRAM apos merge nunca pode superar a VRAM antes do merge.",\n        "",\n        "ESTRUTURA",\n        f"  TPIs totais: {len(items)}",\n        f"  Texture Pages originais: {original_total_pages}",\n        f"  Texture Pages antes do coalescing: {pre_coalesce_count}",\n        f"  Texture Pages novas propostas: {new_total_pages}",\n        f"  Merges zero-cost aplicados: {len(coalesce_history)}",\n        "",\n        "2048x2048",\n        f"  Paginas originais ~2048: {original_2048_pages}",\n        f"  Novas paginas 2048:      {new_2048_pages}",\n        f"  2048 gratuitos:          {len(gratuitous_2048)}",\n        "",\n        "ROOMS",\n        f"  Melhoradas em VRAM: {len(improved)}",\n        f"  Iguais em VRAM:     {len(equal)}",\n        f"  Piores em VRAM:     {len(worse)}",\n        "",\n        "ATLAS POR ROOM",\n        f"  Menos atlas: {rooms_fewer_atlases}",\n        f"  Mesmo numero: {rooms_same_atlases}",\n        f"  Mais atlas: {rooms_more_atlases}",\n        f"  Media original: {avg_original_atlases:.3f}",\n        f"  Media nova:     {avg_new_atlases:.3f}",\n        "",\n        "RGBA4444",\n        f"  Peak antes:  {peak_before:.3f} MiB",\n        f"  Peak depois: {peak_after:.3f} MiB",\n        f"  Peak saving: {peak_before - peak_after:.3f} MiB",\n        f"  Saving acumulado: {total_before - total_after:.3f} MiB-room",\n        "",\n        "DENSIDADE / TAMANHO FISICO",\n        f"  Pixels totais de canvas: {total_canvas_pixels:,}",\n        f"  Pixels efetivos de TPIs: {total_tpi_pixels:,}",\n        f"  Ocupacao global:          {global_canvas_occupancy * 100.0:.2f}%",\n        f"  Equiv. canvas RGBA8888:   {canvas_rgba8888_mib:.2f} MiB",\n        f"  Equiv. canvas RGBA4444:   {canvas_rgba4444_mib:.2f} MiB",\n        "",\n        "V5.5 HYBRID / UNKNOWN",\n        f"  TPIs sem Room conhecida:              {unknown_tpi_count}",\n        f"  Source pages originais unknown:       {len(unknown_source_pages)}",\n        f"  Atlas finais sem Room conhecida:      {len(unknown_final_atlases)}",\n        f"  Atlas finais com Room conhecida:      {len(known_final_atlases)}",\n        f"  Atlas hibridos por source page:       {len(hybrid_unknown_atlases)}",\n        f"  Atlas finais com apenas 1 TPI:        {len(single_tpi_atlases)}",\n        f"  Canvas unknown final:                 {unknown_final_canvas_pixels:,} pixels",\n        "",\n        "DISTRIBUICAO DE NOVOS ATLAS",\n    ]\n\n    for size in ATLAS_SIZES:\n        lines.append(\n            f"  {size}x{size}: {size_distribution.get(size, 0)}"\n        )\n\n    lines += [\n        "",\n        "CRITERIO DE APROVACAO RECOMENDADO",\n        "  - 0 paginas 2048 que nao sejam forçadas por TPI >1024.",\n        "  - Idealmente 0 Rooms piores.",\n        "  - Peak RGBA4444 menor que o baseline.",\n        "  - New atlas count por Room preferencialmente <= original atlas count.",\n        "",\n        "ARQUIVOS",\n        "  global_atlas_plan.csv",\n        "  global_item_manifest.csv",\n        "  room_global_before_after.csv",\n        "  atlas_size_distribution.csv",\n        "  atlas_density.csv",\n        "  global_repack_plan.json",\n        "  coalesce_history.csv",\n    ]\n\n    (OUTPUT_DIR / "summary_v5_5_hybrid.txt").write_text(\n        "\\n".join(lines),\n        encoding="utf-8",\n    )\n\n    progress(99.5, "Arquivos gerados. Finalizando...")\n    progress(100.0, "Analise concluida.")\n\n    print("=" * 104, flush=True)\n    print("GLOBAL TEXTURE REPACK ANALYZER V5.5 HYBRID UNKNOWN-SOURCE SAFE CONCLUIDO", flush=True)\n    print("=" * 104)\n    print()\n    print(f"TPIs totais:                 {len(items)}")\n    print(f"Texture Pages originais:     {original_total_pages}")\n    print(f"Texture Pages pre-merge:     {pre_coalesce_count}")\n    print(f"Texture Pages novas:         {new_total_pages}")\n    print(f"Merges zero-cost:            {len(coalesce_history)}")\n    print()\n    print(f"2048 originais:              {original_2048_pages}")\n    print(f"2048 novas:                  {new_2048_pages}")\n    print(f"2048 gratuitos:              {len(gratuitous_2048)}")\n    print()\n    print(f"Rooms melhoradas:            {len(improved)}")\n    print(f"Rooms piores VRAM:           {len(worse)}")\n    print()\n    print(f"Rooms com menos atlas:       {rooms_fewer_atlases}")\n    print(f"Rooms com mesmo numero:      {rooms_same_atlases}")\n    print(f"Rooms com mais atlas:        {rooms_more_atlases}")\n    print(f"Media atlas/Room original:   {avg_original_atlases:.3f}")\n    print(f"Media atlas/Room nova:       {avg_new_atlases:.3f}")\n    print()\n    print(\n        f"Peak RGBA4444:               "\n        f"{peak_before:.3f} -> {peak_after:.3f} MiB"\n    )\n    print(\n        f"Economia peak:               "\n        f"{peak_before - peak_after:.3f} MiB"\n    )\n    print()\n    print(\n        f"Canvas total:                 "\n        f"{total_canvas_pixels:,} pixels"\n    )\n    print(\n        f"Ocupacao global:              "\n        f"{global_canvas_occupancy * 100.0:.2f}%"\n    )\n    print(\n        f"Equiv. canvas RGBA8888:       "\n        f"{canvas_rgba8888_mib:.2f} MiB"\n    )\n    print()\n    print(f"TPIs sem Room conhecida:      {unknown_tpi_count}")\n    print(f"Source pages unknown:         {len(unknown_source_pages)}")\n    print(f"Atlas finais unknown:         {len(unknown_final_atlases)}")\n    print(f"Atlas finais conhecidos:      {len(known_final_atlases)}")\n    print(f"Atlas com apenas 1 TPI:       {len(single_tpi_atlases)}")\n    print()\n    print("Distribuicao de novos atlas:")\n\n    for size in ATLAS_SIZES:\n        print(\n            f"  {size:4d}x{size:<4d}: "\n            f"{size_distribution.get(size, 0)}"\n        )\n\n    print()\n    print(f"Arquivos gerados em:")\n    print(OUTPUT_DIR)\n    print()\n    print("Me envie principalmente:")\n    print("  summary_v5_5_hybrid.txt")\n    print("  atlas_size_distribution.csv")\n    print("  atlas_density.csv")\n    print("  room_global_before_after.csv")\n    print("  global_atlas_plan.csv")\n    print()\n    print("Nenhuma alteracao foi feita no data.win.")\n\n    return 0\n\n\nif __name__ == "__main__":\n    sys.exit(main())\n'
WRITER_SOURCE = 'import csv\nimport hashlib\nimport json\nimport shutil\nimport subprocess\nimport sys\nimport time\nfrom pathlib import Path\n\nBASE_DIR = Path(r"C:\\Users\\wolff\\Documents\\SDKVita\\DeltaruneVita\\data\\Teste")\n\nORIGINAL_DATA = BASE_DIR / "data.win"\nPLAN_DIR = BASE_DIR / "vita_texture_analysis_v5_6_texturegroup_safe"\nPLAN_JSON = PLAN_DIR / "global_repack_plan.json"\n\nWORK_DIR = BASE_DIR / "vita_texture_repack_v0_72_alpha_v56"\nWORKING_SOURCE = WORK_DIR / "data_v0_72_alpha_v56_source_copy.win"\nOUTPUT_DATA = WORK_DIR / "data_v0_72_alpha_v56.win"\n\nATLAS_MANIFEST = WORK_DIR / "_v0_72_atlases.tsv"\nITEM_MANIFEST = WORK_DIR / "_v0_72_items.tsv"\nAPPLY_CSX = WORK_DIR / "_apply_v0_72_alpha_rawcrop.csx"\nVERIFY_CSX = WORK_DIR / "_verify_v0_72_alpha.csx"\nLOG_FILE = WORK_DIR / "v0_72_alpha_repack_log.txt"\nPROGRESS_FILE = WORK_DIR / "v0_72_alpha_progress.txt"\n\nEXPECTED_ORIGINAL_TEXTURE_PAGES = 27\nEXPECTED_TPIS = 9538\nEXPECTED_NEW_ATLASES = 556\nALLOWED_ATLAS_SIZES = {64, 128, 256, 512, 1024, 2048}\n\nALLOW_OVERWRITE_OUTPUT = False\nALLOW_CROSS_TEXTURE_GROUP = False\n\nSTART_TIME = time.time()\n\n\ndef log(message=""):\n    text = str(message)\n    print(text, flush=True)\n    with LOG_FILE.open("a", encoding="utf-8") as f:\n        f.write(text + "\\n")\n\n\ndef progress(percent, message):\n    percent = max(0.0, min(100.0, float(percent)))\n    elapsed = time.time() - START_TIME\n    text = f"[{percent:6.2f}%] {message} | {elapsed:,.1f}s"\n    print(text, flush=True)\n    try:\n        PROGRESS_FILE.write_text(text + "\\n", encoding="utf-8")\n    except Exception:\n        pass\n\n\ndef sha256(path: Path, chunk_size=1024 * 1024):\n    h = hashlib.sha256()\n    with path.open("rb") as f:\n        while True:\n            block = f.read(chunk_size)\n            if not block:\n                break\n            h.update(block)\n    return h.hexdigest()\n\n\ndef find_cli():\n    preferred = (\n        BASE_DIR\n        / "UTMT_CLI_v0.9.1.2-Windows"\n        / "UndertaleModCli.exe"\n    )\n    if preferred.exists():\n        return preferred\n\n    for root in [BASE_DIR, BASE_DIR.parent, Path(__file__).resolve().parent]:\n        if not root.exists():\n            continue\n        try:\n            matches = list(root.rglob("UndertaleModCli.exe"))\n        except Exception:\n            matches = []\n        if matches:\n            matches.sort(\n                key=lambda p: (\n                    "v0.9.1.2" not in str(p),\n                    len(str(p)),\n                )\n            )\n            return matches[0]\n\n    return preferred\n\n\ndef load_plan():\n    if not PLAN_JSON.exists():\n        raise RuntimeError(f"Plano nao encontrado:\\n{PLAN_JSON}")\n\n    plan = json.loads(PLAN_JSON.read_text(encoding="utf-8"))\n\n    version = str(plan.get("version", ""))\n    if version and version != "5.6-texturegroup-safe":\n        raise RuntimeError(f"Versao inesperada do plano: {version}")\n\n    atlases = plan.get("atlas_plan")\n    if not isinstance(atlases, list):\n        raise RuntimeError("global_repack_plan.json sem atlas_plan.")\n\n    if len(atlases) != EXPECTED_NEW_ATLASES:\n        raise RuntimeError(\n            f"Plano possui {len(atlases)} atlas; "\n            f"esperado {EXPECTED_NEW_ATLASES}."\n        )\n\n    seen = set()\n    distribution = {}\n\n    for atlas in atlases:\n        atlas_id = str(atlas["atlas_id"])\n        size = int(atlas["size"])\n\n        if size not in ALLOWED_ATLAS_SIZES:\n            raise RuntimeError(f"Atlas {atlas_id}: tamanho invalido {size}.")\n\n        distribution[size] = distribution.get(size, 0) + 1\n\n        if size == 2048 and not atlas.get("forced_2048"):\n            raise RuntimeError(f"Atlas 2048 gratuito detectado: {atlas_id}")\n\n        items = atlas.get("items", [])\n        if not items:\n            raise RuntimeError(f"Atlas vazio: {atlas_id}")\n\n        for item in items:\n            tid = int(item["item"])\n            source_page = int(item["source_page"])\n            x = int(item["new_x"])\n            y = int(item["new_y"])\n            w = int(item["width"])\n            h = int(item["height"])\n\n            if tid in seen:\n                raise RuntimeError(f"TPI duplicado no plano: {tid}")\n            seen.add(tid)\n\n            if not (0 <= source_page < EXPECTED_ORIGINAL_TEXTURE_PAGES):\n                raise RuntimeError(\n                    f"TPI {tid}: source_page invalida {source_page}."\n                )\n\n            if x < 0 or y < 0 or x + w > size or y + h > size:\n                raise RuntimeError(\n                    f"TPI {tid} fora de {atlas_id} ({size}x{size})."\n                )\n\n    expected = set(range(EXPECTED_TPIS))\n    if seen != expected:\n        missing = sorted(expected - seen)\n        extra = sorted(seen - expected)\n        raise RuntimeError(\n            "Plano nao cobre exatamente TPIs 0..9537. "\n            f"Missing={missing[:20]} Extra={extra[:20]}"\n        )\n\n    return plan, atlases, distribution\n\n\ndef write_manifests(atlases):\n    with ATLAS_MANIFEST.open("w", encoding="utf-8", newline="") as f:\n        w = csv.writer(f, delimiter="\\t", lineterminator="\\n")\n        w.writerow(["atlas_id", "size", "first_tpi"])\n        for atlas in atlases:\n            w.writerow([\n                str(atlas["atlas_id"]),\n                int(atlas["size"]),\n                int(atlas["items"][0]["item"]),\n            ])\n\n    with ITEM_MANIFEST.open("w", encoding="utf-8", newline="") as f:\n        w = csv.writer(f, delimiter="\\t", lineterminator="\\n")\n        w.writerow([\n            "atlas_id",\n            "tpi",\n            "source_page",\n            "new_x",\n            "new_y",\n            "width",\n            "height",\n        ])\n        for atlas in atlases:\n            atlas_id = str(atlas["atlas_id"])\n            for item in atlas["items"]:\n                w.writerow([\n                    atlas_id,\n                    int(item["item"]),\n                    int(item["source_page"]),\n                    int(item["new_x"]),\n                    int(item["new_y"]),\n                    int(item["width"]),\n                    int(item["height"]),\n                ])\n\n\ndef cs_quote(value):\n    s = str(value).replace("\\\\", "\\\\\\\\").replace(\'"\', \'\\\\"\')\n    return \'"\' + s + \'"\'\n\n\ndef generate_apply_csx():\n    atlas_manifest = cs_quote(ATLAS_MANIFEST)\n    item_manifest = cs_quote(ITEM_MANIFEST)\n\n    return f\'\'\'using System;\nusing System.IO;\nusing System.Linq;\nusing System.Collections.Generic;\nusing UndertaleModLib.Models;\nusing UndertaleModLib.Util;\nusing ImageMagick;\n\nEnsureDataLoaded();\n\nScriptMessage("v0.72-alpha RAW CROP: inicio.");\n\nif (Data.EmbeddedTextures.Count != {EXPECTED_ORIGINAL_TEXTURE_PAGES})\n    throw new Exception("EmbeddedTextures originais invalidas: " + Data.EmbeddedTextures.Count);\n\nif (Data.TexturePageItems.Count != {EXPECTED_TPIS})\n    throw new Exception("TPIs invalidos: " + Data.TexturePageItems.Count);\n\nvar originalPages = Data.EmbeddedTextures.ToList();\n\ntry\n{{\n    UndertaleEmbeddedTexture.FindAllTextureInfo(Data);\n}}\ncatch\n{{\n}}\n\nstring atlasManifestPath = {atlas_manifest};\nstring itemManifestPath = {item_manifest};\n\nvar atlasRows = File.ReadAllLines(atlasManifestPath)\n    .Skip(1)\n    .Where(x => !String.IsNullOrWhiteSpace(x))\n    .Select(x => x.Split(\'\\\\t\'))\n    .ToList();\n\nvar itemRows = File.ReadAllLines(itemManifestPath)\n    .Skip(1)\n    .Where(x => !String.IsNullOrWhiteSpace(x))\n    .Select(x => x.Split(\'\\\\t\'))\n    .ToList();\n\nif (atlasRows.Count != {EXPECTED_NEW_ATLASES})\n    throw new Exception("Atlas manifest invalidos: " + atlasRows.Count);\n\nif (itemRows.Count != {EXPECTED_TPIS})\n    throw new Exception("Item manifest invalidos: " + itemRows.Count);\n\nvar itemGroups = itemRows\n    .GroupBy(r => r[0])\n    .ToDictionary(g => g.Key, g => g.ToList());\n\nvar newPages = new Dictionary<string, UndertaleEmbeddedTexture>();\n\nScriptMessage("v0.72-alpha: preflight...");\n\nforeach (var atlasRow in atlasRows)\n{{\n    string atlasId = atlasRow[0];\n    var rows = itemGroups[atlasId];\n\n    object groupRef = null;\n    bool groupRefSet = false;\n\n    foreach (var r in rows)\n    {{\n        int tid = Int32.Parse(r[1]);\n        int expectedSourcePage = Int32.Parse(r[2]);\n        int expectedW = Int32.Parse(r[5]);\n        int expectedH = Int32.Parse(r[6]);\n\n        var tpi = Data.TexturePageItems[tid];\n\n        int actualSourcePage =\n            Data.EmbeddedTextures.IndexOf(tpi.TexturePage);\n\n        if (actualSourcePage != expectedSourcePage)\n            throw new Exception(\n                "TPI " + tid + ": source page diferente do plano."\n            );\n\n        if (tpi.SourceWidth != expectedW || tpi.SourceHeight != expectedH)\n            throw new Exception(\n                "TPI " + tid + ": dimensoes diferentes do plano."\n            );\n\n        object currentGroup = null;\n\n        try\n        {{\n            currentGroup = tpi.TexturePage.TextureInfo;\n        }}\n        catch\n        {{\n        }}\n\n        if (!groupRefSet)\n        {{\n            groupRef = currentGroup;\n            groupRefSet = true;\n        }}\n        else\n        {{\n            if (!Object.ReferenceEquals(groupRef, currentGroup))\n                throw new Exception(\n                    "Atlas " + atlasId\n                    + ": mistura TextureInfo/TextureGroup."\n                );\n        }}\n    }}\n}}\n\nvar worker = new TextureWorker();\nvar decodedPages =\n    new Dictionary<UndertaleEmbeddedTexture, MagickImage>();\n\nMagickImage GetDecodedPage(UndertaleEmbeddedTexture oldPage)\n{{\n    if (decodedPages.ContainsKey(oldPage))\n        return decodedPages[oldPage];\n\n    var decoded = worker.GetEmbeddedTexture(oldPage);\n\n    if (decoded == null)\n        throw new Exception("GetEmbeddedTexture retornou null.");\n\n    decodedPages[oldPage] = decoded;\n    return decoded;\n}}\n\nScriptMessage("v0.72-alpha: construindo atlas...");\n\nint atlasDone = 0;\nint itemDone = 0;\n\nforeach (var atlasRow in atlasRows)\n{{\n    string atlasId = atlasRow[0];\n    int atlasSize = Int32.Parse(atlasRow[1]);\n    int firstTid = Int32.Parse(atlasRow[2]);\n\n    var rows = itemGroups[atlasId];\n\n    var representative = Data.TexturePageItems[firstTid];\n    var representativeSourcePage = representative.TexturePage;\n\n    var atlasImage = new MagickImage(\n        MagickColors.Transparent,\n        (uint)atlasSize,\n        (uint)atlasSize\n    );\n\n    foreach (var r in rows)\n    {{\n        int tid = Int32.Parse(r[1]);\n        int sourcePageIndex = Int32.Parse(r[2]);\n        int dstX = Int32.Parse(r[3]);\n        int dstY = Int32.Parse(r[4]);\n        int srcW = Int32.Parse(r[5]);\n        int srcH = Int32.Parse(r[6]);\n\n        var tpi = Data.TexturePageItems[tid];\n\n        int srcX = tpi.SourceX;\n        int srcY = tpi.SourceY;\n\n        var oldPage = originalPages[sourcePageIndex];\n        var fullPage = GetDecodedPage(oldPage);\n\n        if (\n            srcX < 0\n            || srcY < 0\n            || srcX + srcW > (int)fullPage.Width\n            || srcY + srcH > (int)fullPage.Height\n        )\n        {{\n            atlasImage.Dispose();\n            throw new Exception(\n                "TPI " + tid + ": RAW crop fora da pagina original."\n            );\n        }}\n\n        var source = (MagickImage)fullPage.Clone();\n\n        source.Crop(\n            new MagickGeometry(\n                srcX,\n                srcY,\n                (uint)srcW,\n                (uint)srcH\n            )\n        );\n\n        if ((int)source.Width != srcW || (int)source.Height != srcH)\n        {{\n            source.Dispose();\n            atlasImage.Dispose();\n            throw new Exception(\n                "TPI " + tid + ": RAW crop com dimensao inesperada."\n            );\n        }}\n\n        atlasImage.Composite(\n            source,\n            dstX,\n            dstY,\n            CompositeOperator.Copy\n        );\n\n        source.Dispose();\n\n        itemDone++;\n\n        if (itemDone % 250 == 0 || itemDone == {EXPECTED_TPIS})\n            ScriptMessage(\n                "v0.72-alpha build: "\n                + itemDone + "/{EXPECTED_TPIS} TPIs"\n            );\n    }}\n\n    var tex = new UndertaleEmbeddedTexture();\n\n    tex.Name = new UndertaleString(\n        "Texture " + Data.EmbeddedTextures.Count\n    );\n\n    tex.Scaled = representativeSourcePage.Scaled;\n    tex.GeneratedMips = representativeSourcePage.GeneratedMips;\n    tex.TextureWidth = atlasSize;\n    tex.TextureHeight = atlasSize;\n\n    tex.TextureData.Image =\n        GMImage.FromMagickImage(atlasImage).ConvertToPng();\n\n    atlasImage.Dispose();\n\n    try\n    {{\n        tex.TextureInfo = representativeSourcePage.TextureInfo;\n\n        if (tex.TextureInfo != null)\n        {{\n            tex.TextureInfo.TexturePages.Add(\n                new UndertaleResourceById<\n                    UndertaleEmbeddedTexture,\n                    UndertaleChunkTXTR\n                >()\n                {{\n                    Resource = tex\n                }}\n            );\n        }}\n    }}\n    catch\n    {{\n    }}\n\n    Data.EmbeddedTextures.Add(tex);\n    newPages[atlasId] = tex;\n\n    atlasDone++;\n\n    if (atlasDone % 20 == 0 || atlasDone == {EXPECTED_NEW_ATLASES})\n        ScriptMessage(\n            "v0.72-alpha atlas: "\n            + atlasDone + "/{EXPECTED_NEW_ATLASES}"\n        );\n}}\n\nforeach (var kv in decodedPages)\n{{\n    try\n    {{\n        kv.Value.Dispose();\n    }}\n    catch\n    {{\n    }}\n}}\n\ndecodedPages.Clear();\n\ntry\n{{\n    worker.Dispose();\n}}\ncatch\n{{\n}}\n\nScriptMessage("v0.72-alpha: remapeando TPIs...");\n\nint remapped = 0;\n\nforeach (var r in itemRows)\n{{\n    string atlasId = r[0];\n    int tid = Int32.Parse(r[1]);\n    int dstX = Int32.Parse(r[3]);\n    int dstY = Int32.Parse(r[4]);\n    int srcW = Int32.Parse(r[5]);\n    int srcH = Int32.Parse(r[6]);\n\n    var tpi = Data.TexturePageItems[tid];\n\n    tpi.TexturePage = newPages[atlasId];\n    tpi.SourceX = (ushort)dstX;\n    tpi.SourceY = (ushort)dstY;\n    tpi.SourceWidth = (ushort)srcW;\n    tpi.SourceHeight = (ushort)srcH;\n\n    remapped++;\n\n    if (remapped % 500 == 0 || remapped == {EXPECTED_TPIS})\n        ScriptMessage(\n            "v0.72-alpha remap: "\n            + remapped + "/{EXPECTED_TPIS}"\n        );\n}}\n\nfor (int i = 0; i < Data.TexturePageItems.Count; i++)\n{{\n    if (originalPages.Contains(Data.TexturePageItems[i].TexturePage))\n        throw new Exception(\n            "TPI " + i + " ainda aponta para pagina original."\n        );\n}}\n\nScriptMessage("v0.72-alpha: removendo paginas originais...");\n\nforeach (var oldPage in originalPages)\n{{\n    try\n    {{\n        if (oldPage.TextureInfo != null)\n        {{\n            var refs = oldPage.TextureInfo.TexturePages\n                .Where(x => Object.ReferenceEquals(x.Resource, oldPage))\n                .ToList();\n\n            foreach (var r in refs)\n                oldPage.TextureInfo.TexturePages.Remove(r);\n        }}\n    }}\n    catch\n    {{\n    }}\n\n    Data.EmbeddedTextures.Remove(oldPage);\n}}\n\nif (Data.EmbeddedTextures.Count != {EXPECTED_NEW_ATLASES})\n    throw new Exception(\n        "Contagem final invalida de EmbeddedTextures: "\n        + Data.EmbeddedTextures.Count\n    );\n\nScriptMessage(\n    "v0.72-alpha RAW CROP OK: "\n    + Data.EmbeddedTextures.Count\n    + " texture pages; "\n    + Data.TexturePageItems.Count\n    + " TPIs."\n);\n\'\'\'\n\n\ndef generate_verify_csx():\n    atlas_manifest = cs_quote(ATLAS_MANIFEST)\n    item_manifest = cs_quote(ITEM_MANIFEST)\n\n    return f\'\'\'using System;\nusing System.IO;\nusing System.Linq;\nusing System.Collections.Generic;\nusing UndertaleModLib.Models;\n\nEnsureDataLoaded();\n\nif (Data.TexturePageItems.Count != {EXPECTED_TPIS})\n    throw new Exception(\n        "TPIs invalidos apos reload: "\n        + Data.TexturePageItems.Count\n    );\n\nif (Data.EmbeddedTextures.Count != {EXPECTED_NEW_ATLASES})\n    throw new Exception(\n        "EmbeddedTextures invalidas apos reload: "\n        + Data.EmbeddedTextures.Count\n    );\n\nstring atlasManifestPath = {atlas_manifest};\nstring itemManifestPath = {item_manifest};\n\nvar atlasRows = File.ReadAllLines(atlasManifestPath)\n    .Skip(1)\n    .Where(x => !String.IsNullOrWhiteSpace(x))\n    .Select(x => x.Split(\'\\\\t\'))\n    .ToList();\n\nvar itemRows = File.ReadAllLines(itemManifestPath)\n    .Skip(1)\n    .Where(x => !String.IsNullOrWhiteSpace(x))\n    .Select(x => x.Split(\'\\\\t\'))\n    .ToList();\n\nvar itemGroups = itemRows\n    .GroupBy(r => r[0])\n    .ToDictionary(g => g.Key, g => g.ToList());\n\nint checkedItems = 0;\n\nforeach (var atlasRow in atlasRows)\n{{\n    string atlasId = atlasRow[0];\n    int expectedSize = Int32.Parse(atlasRow[1]);\n    int firstTid = Int32.Parse(atlasRow[2]);\n\n    var page = Data.TexturePageItems[firstTid].TexturePage;\n\n    if (Data.EmbeddedTextures.IndexOf(page) < 0)\n        throw new Exception(\n            "Verify: pagina do TPI " + firstTid + " nao existe."\n        );\n\n    if (\n        page.TextureData.Image.Width != expectedSize\n        || page.TextureData.Image.Height != expectedSize\n    )\n        throw new Exception(\n            "Verify: atlas " + atlasId + " possui dimensao incorreta."\n        );\n\n    foreach (var r in itemGroups[atlasId])\n    {{\n        int tid = Int32.Parse(r[1]);\n        int expectedX = Int32.Parse(r[3]);\n        int expectedY = Int32.Parse(r[4]);\n        int expectedW = Int32.Parse(r[5]);\n        int expectedH = Int32.Parse(r[6]);\n\n        var tpi = Data.TexturePageItems[tid];\n\n        if (!Object.ReferenceEquals(tpi.TexturePage, page))\n            throw new Exception(\n                "Verify: TPI " + tid + " aponta para pagina incorreta."\n            );\n\n        if (\n            tpi.SourceX != expectedX\n            || tpi.SourceY != expectedY\n            || tpi.SourceWidth != expectedW\n            || tpi.SourceHeight != expectedH\n        )\n            throw new Exception(\n                "Verify: TPI " + tid + " possui Source* incorreto."\n            );\n\n        checkedItems++;\n\n        if (checkedItems % 700 == 0 || checkedItems == {EXPECTED_TPIS})\n            ScriptMessage(\n                "v0.72-alpha verify: "\n                + checkedItems + "/{EXPECTED_TPIS}"\n            );\n    }}\n}}\n\nif (checkedItems != {EXPECTED_TPIS})\n    throw new Exception(\n        "Verify: apenas "\n        + checkedItems\n        + " TPIs foram verificados."\n    );\n\nScriptMessage(\n    "VERIFICACAO v0.72-alpha OK: todos os {EXPECTED_TPIS} TPIs foram relidos."\n);\n\'\'\'\n\n\ndef run_process_live(cmd, cwd):\n    proc = subprocess.Popen(\n        cmd,\n        cwd=str(cwd),\n        stdout=subprocess.PIPE,\n        stderr=subprocess.STDOUT,\n        text=True,\n        bufsize=1,\n    )\n\n    if proc.stdout is not None:\n        for line in proc.stdout:\n            line = line.rstrip()\n            if not line:\n                continue\n            print(f"[UTMT] {line}", flush=True)\n            with LOG_FILE.open("a", encoding="utf-8") as f:\n                f.write("[UTMT] " + line + "\\n")\n\n    return proc.wait()\n\n\ndef main():\n    WORK_DIR.mkdir(parents=True, exist_ok=True)\n    LOG_FILE.write_text("", encoding="utf-8")\n\n    progress(0.0, "Iniciando v0.72-alpha RAW CROP.")\n\n    cli_exe = find_cli()\n\n    progress(0.2, f"BASE_DIR: {BASE_DIR}")\n    progress(0.3, f"CLI: {cli_exe}")\n    progress(0.4, f"Plano: {PLAN_JSON}")\n\n    required = [ORIGINAL_DATA, PLAN_JSON, cli_exe]\n    missing = [p for p in required if not p.exists()]\n\n    if missing:\n        log("ERRO: arquivos obrigatorios ausentes:")\n        for p in missing:\n            log(f"  - {p}")\n        return 1\n\n    if OUTPUT_DATA.exists() and not ALLOW_OVERWRITE_OUTPUT:\n        log("ERRO: arquivo de saida ja existe:")\n        log(f"  {OUTPUT_DATA}")\n        log("Apague/mova o arquivo antes de rodar novamente.")\n        return 1\n\n    progress(0.5, "Carregando e validando plano v5.6 TextureGroup-safe...")\n\n    try:\n        _, atlases, distribution = load_plan()\n    except Exception as exc:\n        log(f"ERRO NO PLANO: {exc}")\n        return 1\n\n    progress(\n        1.0,\n        f"Plano OK: {EXPECTED_TPIS} TPIs | {EXPECTED_NEW_ATLASES} atlas"\n    )\n\n    log("Distribuicao:")\n    for size in sorted(distribution):\n        log(f"  {size:4d}x{size:<4d}: {distribution[size]}")\n\n    original_hash = sha256(ORIGINAL_DATA)\n\n    log(f"SHA256 original: {original_hash}")\n\n    progress(1.5, "Gerando manifests compactos...")\n    write_manifests(atlases)\n\n    progress(2.0, "Gerando scripts C#...")\n\n    apply_text = generate_apply_csx()\n    verify_text = generate_verify_csx()\n\n    for token in ("using var ", ".RePage(", "worker.ExportAsPNG("):\n        if token in apply_text:\n            raise RuntimeError(\n                f"CSX gerado contem token proibido: {token}"\n            )\n\n    for token in (\n        "GetEmbeddedTexture(oldPage)",\n        "source.Crop(",\n        "CompositeOperator.Copy",\n    ):\n        if token not in apply_text:\n            raise RuntimeError(\n                f"CSX gerado nao contem token obrigatorio: {token}"\n            )\n\n    APPLY_CSX.write_text(apply_text, encoding="utf-8")\n    VERIFY_CSX.write_text(verify_text, encoding="utf-8")\n\n    progress(2.5, "Criando copia de trabalho...")\n\n    shutil.copy2(ORIGINAL_DATA, WORKING_SOURCE)\n\n    if sha256(WORKING_SOURCE) != original_hash:\n        log("ERRO: hash da copia difere do original.")\n        return 1\n\n    progress(3.0, "Executando UndertaleModCli...")\n\n    cmd = [\n        str(cli_exe),\n        "load",\n        str(WORKING_SOURCE),\n        "-s",\n        str(APPLY_CSX),\n        "-o",\n        str(OUTPUT_DATA),\n    ]\n\n    rc = run_process_live(cmd, cli_exe.parent)\n\n    if rc != 0:\n        log(f"ERRO: UndertaleModCli retornou {rc}.")\n        log("Nenhum .win parcial deve ser usado.")\n        return rc or 1\n\n    if not OUTPUT_DATA.exists():\n        log("ERRO: arquivo de saida nao foi criado.")\n        return 1\n\n    progress(90.0, "Build salvo. Calculando SHA256...")\n\n    output_hash = sha256(OUTPUT_DATA)\n\n    log(f"Saida: {OUTPUT_DATA}")\n    log(f"SHA256 saida: {output_hash}")\n\n    progress(92.0, "Reabrindo .win para verificacao completa...")\n\n    verify_cmd = [\n        str(cli_exe),\n        "load",\n        str(OUTPUT_DATA),\n        "-s",\n        str(VERIFY_CSX),\n    ]\n\n    rc = run_process_live(verify_cmd, cli_exe.parent)\n\n    if rc != 0:\n        log("ERRO: .win criado, mas falhou na verificacao.")\n        log("NAO use este arquivo no Vita.")\n        return rc or 1\n\n    if sha256(ORIGINAL_DATA) != original_hash:\n        log("ERRO CRITICO: data.win original foi alterado.")\n        return 1\n\n    output_size_mib = OUTPUT_DATA.stat().st_size / (1024 * 1024)\n\n    progress(100.0, "Concluido.")\n\n    log("=" * 104)\n    log("v0.72-alpha GLOBAL REPACK v5.6 TEXTUREGROUP-SAFE CONCLUIDO")\n    log("=" * 104)\n    log(f"Arquivo de teste: {OUTPUT_DATA}")\n    log(f"Tamanho final: {output_size_mib:.2f} MiB")\n    log(f"SHA256: {output_hash}")\n    log("Original permaneceu intacto.")\n\n    return 0\n\n\nif __name__ == "__main__":\n    sys.exit(main())\n'

ATLAS_SIZES = [64, 128, 256, 512, 1024, 2048]
PADDING = 2


def log(message=""):
    print(str(message), flush=True)


def sha256(path, chunk_size=1024 * 1024):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        while True:
            block = f.read(chunk_size)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def py_literal_path(path):
    # Generated helper scripts must never receive Windows backslashes.
    # Python on Windows accepts forward slashes natively:
    #   C:/Users/name/project/file.win
    # This makes unicodeescape errors such as \UXXXXXXXX impossible.
    value = str(Path(path)).replace("\\", "/")
    value = value.replace('"', '\\"')
    return 'Path("' + value + '")'


def patch_assignment(source, name, expression):
    pattern = rf"^{re.escape(name)}\s*=.*$"
    replacement = f"{name} = {expression}"
    # IMPORTANT:
    # Use a callable replacement so Windows backslashes are inserted
    # literally. Passing the replacement as a string makes re.sub()
    # interpret sequences such as \U, \1, etc.
    out, count = re.subn(
        pattern,
        lambda _match: replacement,
        source,
        count=1,
        flags=re.MULTILINE,
    )
    if count != 1:
        raise RuntimeError(
            f"Nao foi possivel ajustar {name} no helper."
        )
    return out


def run_live(cmd, cwd=None, prefix=""):
    proc = subprocess.Popen(
        [str(x) for x in cmd],
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    if proc.stdout is not None:
        for line in proc.stdout:
            text = line.rstrip()
            if text:
                print(prefix + text, flush=True)
    return proc.wait()


def find_cli(input_win, explicit=None):
    if explicit:
        p = Path(explicit).expanduser().resolve()
        if p.exists():
            return p
        raise RuntimeError(
            f"UndertaleModCli.exe nao encontrado: {p}"
        )

    roots = [
        Path(input_win).resolve().parent,
        Path.cwd(),
        Path(__file__).resolve().parent,
    ]

    candidates = []

    for root in roots:
        if not root.exists():
            continue

        direct = (
            root
            / "UTMT_CLI_v0.9.1.2-Windows"
            / "UndertaleModCli.exe"
        )

        if direct.exists():
            return direct

        try:
            candidates.extend(root.glob("**/UndertaleModCli.exe"))
        except Exception:
            pass

    if candidates:
        candidates.sort(
            key=lambda p: (
                "v0.9.1.2" not in str(p),
                len(str(p)),
            )
        )
        return candidates[0]

    raise RuntimeError(
        "UndertaleModCli.exe nao encontrado. Use --cli CAMINHO."
    )


def write_helper(path, source):
    Path(path).write_text(source, encoding="utf-8")
    compile(source, str(path), "exec")


def stage_raw_analysis(work_root, cli):
    log()
    log("[1/5] RAW ANALYSIS")

    source = V3_SOURCE
    source = patch_assignment(
        source,
        "DATA_WIN",
        py_literal_path(work_root / "data.win"),
    )
    source = patch_assignment(
        source,
        "CLI_FOLDER",
        py_literal_path(cli.parent),
    )
    source = patch_assignment(
        source,
        "OUTPUT_DIR",
        py_literal_path(work_root / "vita_texture_analysis_v3"),
    )

    helper = work_root / "_stage1_raw_analysis.py"
    write_helper(helper, source)

    rc = run_live(
        [sys.executable, helper],
        cwd=work_root,
        prefix="[RAW] ",
    )

    if rc != 0:
        raise RuntimeError(f"Raw analyzer retornou {rc}.")

    raw_json = (
        work_root
        / "vita_texture_analysis_v3"
        / "raw_texture_analysis_v3.json"
    )

    if not raw_json.exists():
        raise RuntimeError(
            "raw_texture_analysis_v3.json nao foi gerado."
        )

    raw = json.loads(
        raw_json.read_text(encoding="utf-8-sig")
    )

    pages = len(raw.get("pages", []))
    items = len(raw.get("items", []))
    rooms = len(raw.get("rooms", []))

    if pages <= 0 or items <= 0:
        raise RuntimeError(
            "Raw analysis nao retornou pages/TPIs validos."
        )

    log(
        f"[RAW] OK: {pages} pages | "
        f"{items} TPIs | {rooms} Rooms"
    )

    return raw_json, raw


def stage_v55_plan(work_root):
    log()
    log("[2/5] HYBRID / DENSITY-AWARE PLAN")

    source = V55_SOURCE
    source = patch_assignment(
        source,
        "BASE_DIR",
        py_literal_path(work_root),
    )
    source = patch_assignment(
        source,
        "V3_DIR",
        py_literal_path(work_root / "vita_texture_analysis_v3"),
    )
    source = patch_assignment(
        source,
        "RAW_JSON",
        py_literal_path(
            work_root
            / "vita_texture_analysis_v3"
            / "raw_texture_analysis_v3.json"
        ),
    )
    source = patch_assignment(
        source,
        "OUTPUT_DIR",
        py_literal_path(
            work_root
            / "vita_texture_analysis_v5_5_hybrid_unknown_source_safe"
        ),
    )

    helper = work_root / "_stage2_v55_plan.py"
    write_helper(helper, source)

    rc = run_live(
        [sys.executable, helper],
        cwd=work_root,
        prefix="[PLAN] ",
    )

    if rc != 0:
        raise RuntimeError(f"Planner retornou {rc}.")

    plan_path = (
        work_root
        / "vita_texture_analysis_v5_5_hybrid_unknown_source_safe"
        / "global_repack_plan.json"
    )

    if not plan_path.exists():
        raise RuntimeError(
            "global_repack_plan.json v5.5 nao foi gerado."
        )

    return plan_path


def generate_group_probe_csx(output_tsv, expected_tpis, expected_pages):
    output_cs = (
        str(output_tsv)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
    )

    csx = r'''using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using UndertaleModLib.Models;

EnsureDataLoaded();

if (Data.TexturePageItems.Count != __EXPECTED_TPIS__)
    throw new Exception(
        "TPIs inesperados: " + Data.TexturePageItems.Count
    );

if (Data.EmbeddedTextures.Count != __EXPECTED_PAGES__)
    throw new Exception(
        "EmbeddedTextures inesperadas: " + Data.EmbeddedTextures.Count
    );

try
{
    UndertaleEmbeddedTexture.FindAllTextureInfo(Data);
}
catch
{
}

var textureInfos = new List<object>();

string GetGroupId(UndertaleEmbeddedTexture page)
{
    object info = null;

    try
    {
        info = page.TextureInfo;
    }
    catch
    {
    }

    if (info == null)
        return "NULL";

    for (int i = 0; i < textureInfos.Count; i++)
    {
        if (Object.ReferenceEquals(textureInfos[i], info))
            return "G" + i.ToString("D3");
    }

    textureInfos.Add(info);
    return "G" + (textureInfos.Count - 1).ToString("D3");
}

var lines = new List<string>();
lines.Add("tpi\tsource_page\ttexture_group");

for (int i = 0; i < Data.TexturePageItems.Count; i++)
{
    var tpi = Data.TexturePageItems[i];

    int sourcePage =
        Data.EmbeddedTextures.IndexOf(tpi.TexturePage);

    lines.Add(
        i + "\t"
        + sourcePage + "\t"
        + GetGroupId(tpi.TexturePage)
    );

    if (
        i % 1000 == 0
        || i == Data.TexturePageItems.Count - 1
    )
        ScriptMessage(
            "TextureGroup probe: "
            + (i + 1) + "/__EXPECTED_TPIS__"
        );
}

File.WriteAllLines(
    "__OUTPUT_TSV__",
    lines
);

ScriptMessage(
    "TEXTURE GROUP PROBE OK: "
    + Data.TexturePageItems.Count
    + " TPIs | "
    + textureInfos.Count
    + " grupos nao-null."
);
'''

    return (
        csx
        .replace("__EXPECTED_TPIS__", str(expected_tpis))
        .replace("__EXPECTED_PAGES__", str(expected_pages))
        .replace("__OUTPUT_TSV__", output_cs)
    )


def stage_group_probe(work_root, cli, raw):
    log()
    log("[3/5] TEXTURE GROUP PROBE")

    out_dir = work_root / "vita_texture_group_probe"
    out_dir.mkdir(parents=True, exist_ok=True)

    tsv = out_dir / "tpi_texture_groups.tsv"
    csx = out_dir / "_probe_texture_groups.csx"

    expected_tpis = len(raw["items"])
    expected_pages = len(raw["pages"])

    csx.write_text(
        generate_group_probe_csx(
            tsv,
            expected_tpis,
            expected_pages,
        ),
        encoding="utf-8",
    )

    rc = run_live(
        [
            cli,
            "load",
            work_root / "data.win",
            "-s",
            csx,
        ],
        cwd=cli.parent,
        prefix="[GROUP] ",
    )

    if rc != 0:
        raise RuntimeError(
            f"TextureGroup probe retornou {rc}."
        )

    if not tsv.exists():
        raise RuntimeError(
            "tpi_texture_groups.tsv nao foi gerado."
        )

    with tsv.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as f:
        rows = list(csv.DictReader(f, delimiter="\t"))

    if len(rows) != expected_tpis:
        raise RuntimeError(
            f"Probe retornou {len(rows)} TPIs; "
            f"esperado {expected_tpis}."
        )

    dist = Counter(r["texture_group"] for r in rows)

    log(
        "[GROUP] "
        + " | ".join(
            f"{k}={v}"
            for k, v in sorted(dist.items())
        )
    )

    return tsv


def pack_subset_preserving_or_smaller(items, original_size):
    ordered = sorted(
        items,
        key=lambda r: (
            -int(r["height"]),
            -int(r["width"]),
            -(int(r["width"]) * int(r["height"])),
            int(r["item"]),
        ),
    )

    def try_size(size):
        shelves = []
        placements = {}

        for rect in ordered:
            tid = int(rect["item"])
            w = int(rect["width"])
            h = int(rect["height"])

            if w > size or h > size:
                return None

            placed = False

            for shelf in shelves:
                x = shelf["x"]
                if x > 0:
                    x += PADDING

                if (
                    h <= shelf["height"]
                    and x + w <= size
                ):
                    placements[tid] = (x, shelf["y"])
                    shelf["x"] = x + w
                    placed = True
                    break

            if placed:
                continue

            y = (
                shelves[-1]["y"]
                + shelves[-1]["height"]
                + PADDING
                if shelves
                else 0
            )

            if y + h > size:
                return None

            shelves.append({
                "x": w,
                "y": y,
                "height": h,
            })
            placements[tid] = (0, y)

        return placements

    for size in ATLAS_SIZES:
        if size > int(original_size):
            break

        placements = try_size(size)

        if placements is not None:
            out_items = []

            for item in items:
                row = dict(item)
                x, y = placements[int(item["item"])]
                row["new_x"] = x
                row["new_y"] = y
                out_items.append(row)

            return size, out_items

    return int(original_size), [dict(x) for x in items]


def stage_texturegroup_safe_plan(work_root, v55_plan_path, group_tsv):
    log()
    log("[4/5] TEXTUREGROUP-SAFE FINAL PLAN")

    plan = json.loads(
        Path(v55_plan_path).read_text(encoding="utf-8")
    )

    with Path(group_tsv).open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as f:
        rows = list(csv.DictReader(f, delimiter="\t"))

    tpi_group = {
        int(r["tpi"]): r["texture_group"]
        for r in rows
    }

    atlases = plan["atlas_plan"]
    mixed = []

    for atlas in atlases:
        groups = sorted({
            tpi_group[int(item["item"])]
            for item in atlas["items"]
        })

        if len(groups) > 1:
            mixed.append((atlas["atlas_id"], groups))

    log(f"[GROUP-SAFE] Atlas mistos: {len(mixed)}")

    final_atlases = []
    replacement_map = {}
    split_history = []
    split_index = 0

    for atlas in atlases:
        groups = sorted({
            tpi_group[int(item["item"])]
            for item in atlas["items"]
        })

        if len(groups) == 1:
            row = dict(atlas)
            row["texture_group"] = groups[0]
            final_atlases.append(row)
            continue

        replacements = []

        for group_id in groups:
            subset = [
                dict(item)
                for item in atlas["items"]
                if tpi_group[int(item["item"])] == group_id
            ]

            size, subset = pack_subset_preserving_or_smaller(
                subset,
                int(atlas["size"]),
            )

            safe_group = re.sub(
                r"[^A-Za-z0-9_]+",
                "_",
                group_id,
            )

            new_id = (
                f"TGSAFE_{split_index:04d}_"
                f"{safe_group}_{size}"
            )
            split_index += 1

            new_atlas = dict(atlas)
            new_atlas["atlas_id"] = new_id
            new_atlas["size"] = size
            new_atlas["items"] = subset
            new_atlas["texture_group"] = group_id
            new_atlas["coalesced_from"] = [atlas["atlas_id"]]

            final_atlases.append(new_atlas)
            replacements.append(new_id)

            split_history.append({
                "old_atlas": atlas["atlas_id"],
                "new_atlas": new_id,
                "texture_group": group_id,
                "size": size,
                "item_count": len(subset),
            })

        replacement_map[atlas["atlas_id"]] = replacements

    seen = []

    for atlas in final_atlases:
        gs = {
            tpi_group[int(item["item"])]
            for item in atlas["items"]
        }

        if len(gs) != 1:
            raise RuntimeError(
                f"Atlas ainda mistura TextureGroup: "
                f"{atlas['atlas_id']}"
            )

        seen.extend(
            int(item["item"])
            for item in atlas["items"]
        )

    expected_tpis = len(tpi_group)

    if (
        len(seen) != expected_tpis
        or len(set(seen)) != expected_tpis
        or sorted(seen) != list(range(expected_tpis))
    ):
        raise RuntimeError(
            "Cobertura TPI invalida apos TextureGroup split."
        )

    size_by_id = {
        a["atlas_id"]: int(a["size"])
        for a in final_atlases
    }

    # ----------------------------------------------------------------------
    # Exact Room-aware TextureGroup split simulation.
    #
    # v1.5 used an intentionally conservative rule:
    #
    #   Room used mixed atlas A
    #       -> charge EVERY replacement generated from A
    #
    # That can produce false regressions. If A contains G005+G006 but the
    # Room only uses TPIs from G005, after the physical split that Room loads
    # only the G005 replacement.
    #
    # v1.6 reads the raw Room -> TPI relation and charges only replacement
    # atlases whose TextureGroup is actually required by a TPI used by that
    # Room.
    #
    # SAFETY FALLBACK:
    # If the plan says a Room uses the old atlas but raw analysis cannot
    # identify any intersecting TPI, retain the v1.5 conservative behavior
    # and charge every replacement for that atlas.
    # ----------------------------------------------------------------------

    raw_path = (
        Path(work_root)
        / "vita_texture_analysis_v3"
        / "raw_texture_analysis_v3.json"
    )

    raw = json.loads(
        raw_path.read_text(encoding="utf-8-sig")
    )

    room_tpis = {
        str(room["room"]): {
            int(tpi)
            for tpi in room.get("texture_items", [])
        }
        for room in raw.get("rooms", [])
    }

    atlas_items = {
        atlas["atlas_id"]: {
            int(item["item"])
            for item in atlas["items"]
        }
        for atlas in atlases
    }

    # For each split source atlas, map TextureGroup -> replacement atlas id.
    replacement_by_group = {}

    for old_atlas_id, replacement_ids in replacement_map.items():
        group_map = {}

        for replacement_id in replacement_ids:
            replacement = next(
                a
                for a in final_atlases
                if a["atlas_id"] == replacement_id
            )
            group_map[str(replacement["texture_group"])] = replacement_id

        replacement_by_group[old_atlas_id] = group_map

    room_results = []
    exact_split_hits = 0
    conservative_split_fallbacks = 0

    for original in plan.get("room_results", []):
        rr = json.loads(json.dumps(original))
        room_name = str(rr.get("room", ""))
        used_tpis = room_tpis.get(room_name, set())
        ids = []

        for atlas_id in rr.get("new_atlases", []):
            if atlas_id not in replacement_map:
                ids.append(atlas_id)
                continue

            relevant_tpis = (
                atlas_items.get(atlas_id, set())
                & used_tpis
            )

            if relevant_tpis:
                required_groups = {
                    str(tpi_group[tpi])
                    for tpi in relevant_tpis
                }

                group_map = replacement_by_group[atlas_id]

                for group_id in sorted(required_groups):
                    replacement_id = group_map.get(group_id)

                    if replacement_id is None:
                        raise RuntimeError(
                            "TextureGroup split inconsistente: "
                            f"Room {room_name} requer grupo {group_id} "
                            f"do atlas {atlas_id}, mas nao existe replacement."
                        )

                    ids.append(replacement_id)

                exact_split_hits += 1
            else:
                # Conservative fallback: never under-estimate a Room when the
                # raw static relation cannot explain why the plan references
                # this atlas.
                ids.extend(replacement_map[atlas_id])
                conservative_split_fallbacks += 1

        ids = sorted(set(ids))

        rr["new_atlases"] = ids
        rr["new_atlas_count"] = len(ids)

        area = sum(size_by_id[x] ** 2 for x in ids)

        rr["after"] = {
            "RGBA8888": area * 4 / (1024 * 1024),
            "RGBA4444": area * 2 / (1024 * 1024),
            "BC3": area * 1 / (1024 * 1024),
            "BC1": area * 0.5 / (1024 * 1024),
        }

        rr["delta_rgba4444"] = (
            rr["after"]["RGBA4444"]
            - rr["before"]["RGBA4444"]
        )

        room_results.append(rr)

    log(
        "[GROUP-SAFE] Room-aware split: "
        f"exact={exact_split_hits} | "
        f"fallback_conservador={conservative_split_fallbacks}"
    )

    worse = [
        r for r in room_results
        if (
            r["after"]["RGBA4444"]
            > r["before"]["RGBA4444"] + 1e-9
        )
    ]

    if worse:
        names = [r.get("room", "?") for r in worse[:20]]
        raise RuntimeError(
            "TextureGroup split criaria regressao de VRAM "
            f"em {len(worse)} Rooms: {names}"
        )

    total_canvas = sum(
        int(a["size"]) ** 2
        for a in final_atlases
    )

    total_tpi_pixels = int(
        plan.get(
            "total_tpi_pixels",
            sum(
                int(item["width"]) * int(item["height"])
                for atlas in final_atlases
                for item in atlas["items"]
            ),
        )
    )

    occupancy = (
        total_tpi_pixels / total_canvas
        if total_canvas
        else 0.0
    )

    out = dict(plan)
    out["version"] = PIPELINE_VERSION
    out["source_version"] = plan.get("version")
    out["texture_group_probe"] = True
    out["texture_group_count"] = len(set(tpi_group.values()))
    out["texture_group_distribution"] = dict(
        sorted(Counter(tpi_group.values()).items())
    )
    out["texturegroup_split_history"] = split_history
    out["total_canvas_pixels"] = total_canvas
    out["total_tpi_pixels"] = total_tpi_pixels
    out["global_canvas_occupancy"] = occupancy
    out["atlas_plan"] = final_atlases
    out["room_results"] = room_results

    output_dir = (
        work_root
        / "vita_texture_analysis_unified_final"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    output_plan = output_dir / "global_repack_plan.json"
    output_plan.write_text(
        json.dumps(
            out,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    improved = [
        r for r in room_results
        if (
            r["after"]["RGBA4444"]
            < r["before"]["RGBA4444"] - 1e-9
        )
    ]

    equal = [
        r for r in room_results
        if abs(
            r["after"]["RGBA4444"]
            - r["before"]["RGBA4444"]
        ) <= 1e-9
    ]

    peak_before = max(
        (r["before"]["RGBA4444"] for r in room_results),
        default=0.0,
    )
    peak_after = max(
        (r["after"]["RGBA4444"] for r in room_results),
        default=0.0,
    )

    summary = (
        "DeltaruneVita - Unified Texture Optimizer\n"
        + "=" * 80 + "\n\n"
        + f"TPIs: {expected_tpis}\n"
        + f"Atlas pre TextureGroup: {len(atlases)}\n"
        + f"Atlas finais: {len(final_atlases)}\n"
        + f"Atlas mistos corrigidos: {len(mixed)}\n"
        + f"Texture Groups: {len(set(tpi_group.values()))}\n\n"
        + f"Rooms melhoradas: {len(improved)}\n"
        + f"Rooms iguais: {len(equal)}\n"
        + "Rooms piores: 0\n\n"
        + f"Peak RGBA4444: "
          f"{peak_before:.3f} -> {peak_after:.3f} MiB\n"
        + f"Canvas total: {total_canvas:,} pixels\n"
        + f"Ocupacao global: {occupancy*100:.2f}%\n"
    )

    (output_dir / "summary_unified.txt").write_text(
        summary,
        encoding="utf-8",
    )

    log(summary.rstrip())

    return output_plan, out


def patch_writer_source(
    work_root,
    cli,
    final_plan,
    original_pages,
    expected_tpis,
    expected_atlases,
):
    source = WRITER_SOURCE

    source = patch_assignment(
        source,
        "BASE_DIR",
        py_literal_path(work_root),
    )

    source = re.sub(
        r'^PLAN_DIR\s*=.*$',
        "PLAN_DIR = " + py_literal_path(Path(final_plan).parent),
        source,
        count=1,
        flags=re.MULTILINE,
    )

    source = patch_assignment(
        source,
        "WORK_DIR",
        py_literal_path(
            work_root / "vita_texture_repack_unified"
        ),
    )

    source = patch_assignment(
        source,
        "EXPECTED_ORIGINAL_TEXTURE_PAGES",
        str(int(original_pages)),
    )
    source = patch_assignment(
        source,
        "EXPECTED_TPIS",
        str(int(expected_tpis)),
    )
    source = patch_assignment(
        source,
        "EXPECTED_NEW_ATLASES",
        str(int(expected_atlases)),
    )

    source = source.replace(
        'version != "5.6-texturegroup-safe"',
        f'version != "{PIPELINE_VERSION}"',
    )

    start = source.find("def find_cli():")
    end = source.find("\n\ndef load_plan():", start)

    if start < 0 or end < 0:
        raise RuntimeError(
            "Nao foi possivel ajustar find_cli do writer."
        )

    explicit_cli_fn = (
        "def find_cli():\n"
        "    return Path(" + repr(str(cli)) + ")\n"
    )

    source = source[:start] + explicit_cli_fn + source[end:]

    source = source.replace(
        '"data_v0_72_alpha_v56_source_copy.win"',
        '"data_unified_source_copy.win"',
    )
    source = source.replace(
        '"data_v0_72_alpha_v56.win"',
        '"data_optimized.win"',
    )

    return source


def stage_write(
    work_root,
    cli,
    final_plan_path,
    raw,
    final_plan,
):
    log()
    log("[5/5] RAW CROP WRITE + RELOAD VERIFY")

    source = patch_writer_source(
        work_root=work_root,
        cli=cli,
        final_plan=final_plan_path,
        original_pages=len(raw["pages"]),
        expected_tpis=len(raw["items"]),
        expected_atlases=len(final_plan["atlas_plan"]),
    )

    helper = work_root / "_stage5_writer.py"
    write_helper(helper, source)

    rc = run_live(
        [sys.executable, helper],
        cwd=work_root,
        prefix="[WRITE] ",
    )

    if rc != 0:
        raise RuntimeError(f"Writer retornou {rc}.")

    output = (
        work_root
        / "vita_texture_repack_unified"
        / "data_optimized.win"
    )

    if not output.exists():
        raise RuntimeError(
            "Writer terminou sem data_optimized.win."
        )

    return output



def analyze_win(input_win, cli, work_root, force_clean=False):
    input_win = Path(input_win).expanduser().resolve()
    cli = Path(cli).expanduser().resolve()
    work_root = Path(work_root).expanduser().resolve()

    if not input_win.exists():
        raise RuntimeError(f"Arquivo nao encontrado: {input_win}")

    if not cli.exists():
        raise RuntimeError(f"UndertaleModCli.exe nao encontrado: {cli}")

    if force_clean and work_root.exists():
        shutil.rmtree(work_root)

    work_root.mkdir(parents=True, exist_ok=True)

    original_hash = sha256(input_win)

    working_input = work_root / "data.win"

    if (
        not working_input.exists()
        or sha256(working_input) != original_hash
    ):
        shutil.copy2(input_win, working_input)

    if sha256(working_input) != original_hash:
        raise RuntimeError(
            "Copia de trabalho difere do original."
        )

    _, raw = stage_raw_analysis(work_root, cli)
    v55_plan = stage_v55_plan(work_root)
    groups = stage_group_probe(work_root, cli, raw)

    final_plan_path, final_plan = stage_texturegroup_safe_plan(
        work_root,
        v55_plan,
        groups,
    )

    if sha256(input_win) != original_hash:
        raise RuntimeError(
            "ERRO: input original foi alterado durante a analise."
        )

    return {
        "input_win": input_win,
        "cli": cli,
        "work_root": work_root,
        "original_hash": original_hash,
        "raw": raw,
        "final_plan_path": final_plan_path,
        "final_plan": final_plan,
        "summary_path": (
            work_root
            / "vita_texture_analysis_unified_final"
            / "summary_unified.txt"
        ),
    }


def write_optimized_win(analysis):
    input_win = Path(analysis["input_win"])
    cli = Path(analysis["cli"])
    work_root = Path(analysis["work_root"])
    original_hash = analysis["original_hash"]
    raw = analysis["raw"]
    final_plan_path = Path(analysis["final_plan_path"])
    final_plan = analysis["final_plan"]

    output = stage_write(
        work_root,
        cli,
        final_plan_path,
        raw,
        final_plan,
    )

    if sha256(input_win) != original_hash:
        raise RuntimeError(
            "ERRO CRITICO: input original foi alterado."
        )

    return output


if __name__ == "__main__":
    print(
        "Este arquivo e uma biblioteca do rebuild_data_win. "
        "Execute ..\\rebuild_data_win.bat."
    )
