using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using System.Reflection;
using UndertaleModLib;
using UndertaleModLib.Models;
using UndertaleModLib.Util;
using ImageMagick;

string outDir = Environment.GetEnvironmentVariable(
    "DELTARUNEVITA_PTC_EXPORT_DIR"
);

if (String.IsNullOrWhiteSpace(outDir))
    throw new Exception(
        "DELTARUNEVITA_PTC_EXPORT_DIR ausente. "
        + "Execute este helper pelo prepare_texture_cache."
    );

outDir = Path.GetFullPath(outDir);

Directory.CreateDirectory(outDir);
Directory.CreateDirectory(Path.Combine(outDir, "png"));
Directory.CreateDirectory(Path.Combine(outDir, "rgba4444"));

var worker = new TextureWorker();
var rows = new List<string>();
rows.Add("page,width,height,raw4444,source_meta");

string DescribeObject(object obj)
{
    if (obj == null) return "";

    var parts = new List<string>();
    Type t = obj.GetType();

    foreach (PropertyInfo p in t.GetProperties(BindingFlags.Instance | BindingFlags.Public))
    {
        string n = p.Name;
        string ln = n.ToLowerInvariant();

        if (!(ln.Contains("offset") || ln.Contains("size") || ln.Contains("length")
              || ln.Contains("position") || ln.Contains("address")))
            continue;

        try
        {
            object v = p.GetValue(obj, null);
            if (v != null)
                parts.Add(n + "=" + v.ToString());
        }
        catch {}
    }

    foreach (FieldInfo f in t.GetFields(BindingFlags.Instance | BindingFlags.Public))
    {
        string n = f.Name;
        string ln = n.ToLowerInvariant();

        if (!(ln.Contains("offset") || ln.Contains("size") || ln.Contains("length")
              || ln.Contains("position") || ln.Contains("address")))
            continue;

        try
        {
            object v = f.GetValue(obj);
            if (v != null)
                parts.Add(n + "=" + v.ToString());
        }
        catch {}
    }

    return String.Join(";", parts);
}

for (int pageId = 0; pageId < Data.EmbeddedTextures.Count; pageId++)
{
    var page = Data.EmbeddedTextures[pageId];
    var image = worker.GetEmbeddedTexture(page);

    if (image == null)
        throw new Exception("Falha ao decodificar EmbeddedTexture " + pageId);

    // Keep the GameMaker RGBA byte values intact. The cache builder explicitly
    // uses sRGB input and sRGB output when producing BC3, avoiding gamma shifts.
    image.Depth = 8;

    int width = (int)image.Width;
    int height = (int)image.Height;

    string pngPath = Path.Combine(
        outDir,
        "png",
        "page_" + pageId.ToString("D3") + ".png"
    );

    image.Write(pngPath, MagickFormat.Png);

    byte[] rgba = image.GetPixels().ToByteArray(PixelMapping.RGBA);
    byte[] packed = new byte[width * height * 2];

    int src = 0;
    int dst = 0;

    while (src + 3 < rgba.Length)
    {
        int r = rgba[src++];
        int g = rgba[src++];
        int b = rgba[src++];
        int a = rgba[src++];

        ushort value = (ushort)(
            ((r >> 4) << 12)
            | ((g >> 4) << 8)
            | ((b >> 4) << 4)
            | ((a == 0) ? 0 : Math.Min(15, (a + 15) >> 4))
        );

        packed[dst++] = (byte)(value & 0xFF);
        packed[dst++] = (byte)((value >> 8) & 0xFF);
    }

    string rawPath = Path.Combine(
        outDir,
        "rgba4444",
        "page_" + pageId.ToString("D3") + ".rgba4444"
    );

    File.WriteAllBytes(rawPath, packed);

    string meta = "";
    try
    {
        meta += "page{" + DescribeObject(page) + "}";
    }
    catch {}

    try
    {
        if (page.TextureData != null)
            meta += "|textureData{" + DescribeObject(page.TextureData) + "}";
    }
    catch {}

    try
    {
        if (page.TextureData != null && page.TextureData.Image != null)
            meta += "|image{" + DescribeObject(page.TextureData.Image) + "}";
    }
    catch {}

    meta = meta.Replace("\"", "\"\"");
    rows.Add(
        pageId + ","
        + width + ","
        + height + ","
        + packed.Length + ",\""
        + meta + "\""
    );

    if ((pageId + 1) % 25 == 0 || pageId + 1 == Data.EmbeddedTextures.Count)
        ScriptMessage("EXPORT " + (pageId + 1) + "/" + Data.EmbeddedTextures.Count);
}

File.WriteAllLines(
    Path.Combine(outDir, "pages.csv"),
    rows.ToArray()
);

// TextureWorker.Cleanup() is not available in all UTMT builds.
// Let the script/process lifetime release worker resources.
ScriptMessage("DONE pages=" + Data.EmbeddedTextures.Count);
