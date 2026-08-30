import csv, json, os, re, shutil, struct, subprocess, sys
from pathlib import Path

APP_VERSION = '0.3.6-r2'
SOURCE_DIR = Path(__file__).resolve().parent
ROOT_DIR = SOURCE_DIR.parent
CHAPTERS_DIR = ROOT_DIR / 'chapters'
PREPARED_DIR = ROOT_DIR / 'prepared'
UTMT = SOURCE_DIR / 'UTMT_CLI' / 'UndertaleModCli.exe'
PVR = SOURCE_DIR / 'PVRTexToolCLI' / 'PVRTexToolCLI.exe'
CSX = SOURCE_DIR / 'export_texture_pages_v0_1.csx'
WIDTH = 88
VTC1, VTC2, VTC5, VTC6 = 0x31435456, 0x32435456, 0x35435456, 0x36435456
PVR3_MAGIC, PVR_BC3, PVR_SRGB = 0x03525650, 11, 1
BC3_INPUT_COLORSPACE = 'sRGB'
BC3_OUTPUT_COLORSPACE = 'sRGB'
BC3_CHANNEL_TYPE = 'UBN'


def clear(): os.system('cls' if os.name == 'nt' else 'clear')

def title(text, subtitle=None):
    clear(); print('='*WIDTH); print(f' DELTARUNEVITA - PREPARE TEXTURE CACHE | v{APP_VERSION}'); print('='*WIDTH); print(); print(' '+text)
    if subtitle: print(' '+subtitle)
    print(); print('-'*WIDTH); print()

def rel(path):
    try: return str(Path(path).resolve().relative_to(ROOT_DIR)).replace('/', '\\')
    except Exception: return Path(path).name

def discover_chapters():
    CHAPTERS_DIR.mkdir(parents=True, exist_ok=True); out=[]
    for d in CHAPTERS_DIR.iterdir():
        if d.is_dir() and (d/'data.win').is_file(): out.append((d.name, d/'data.win'))
    def key(x):
        try: return (0, int(x[0]))
        except Exception: return (1, x[0].lower())
    return sorted(out, key=key)

def u32(b,o): return struct.unpack_from('<I', b, o)[0]
def i32(b,o): return struct.unpack_from('<i', b, o)[0]

def parse_txtr(path):
    b = Path(path).read_bytes()
    if len(b) < 8 or b[:4] != b'FORM': raise RuntimeError('data.win invalido: FORM nao encontrado.')
    pos=8; start=end=None
    while pos+8 <= len(b):
        name=b[pos:pos+4]; size=u32(b,pos+4); s=pos+8; e=s+size
        if e > len(b): raise RuntimeError(f'Chunk {name!r} extrapola o arquivo.')
        if name == b'TXTR': start,end=s,e; break
        pos=e
    if start is None: raise RuntimeError('Chunk TXTR nao encontrado.')
    count=u32(b,start); table=start+4
    if count <= 0 or table+count*4 > end: raise RuntimeError('TXTR count/tabela invalido.')
    ptrs=[u32(b,table+i*4) for i in range(count)]
    nz=[(i,p) for i,p in enumerate(ptrs) if p]
    if len(nz)<2: raise RuntimeError('TXTR insuficiente para detectar layout.')
    stride=None
    for k in range(len(nz)-1):
        i0,p0=nz[k]; i1,p1=nz[k+1]
        if i1==i0+1 and p1>p0: stride=p1-p0; break
    if stride is None: stride=nz[1][1]-nz[0][1]
    if stride != 28: raise RuntimeError(f'Layout TXTR nao suportado: stride={stride}; esperado 28.')
    pages=[]
    for i,p in enumerate(ptrs):
        if p==0:
            pages.append(dict(page=i, external=True, width=0,height=0,blobOffset=0,blobSize=0,boundaryOffset=0)); continue
        if p+28 > len(b): raise RuntimeError(f'TXTR page {i}: entry fora do arquivo.')
        w,h=i32(b,p+12),i32(b,p+16); off=u32(b,p+24)
        # Some translated Chapter 0 files retain placeholder TXTR entries
        # without an embedded payload.  A 0x0 size is valid only for that
        # external form; real embedded pages still require sane dimensions.
        if w == 0 and h == 0:
            # A few translated selectors keep a zero-sized placeholder with a
            # non-zero pointer. It delimits the preceding blob but has no
            # texture to export or cache itself.
            pages.append(dict(page=i, external=True, width=0,height=0,blobOffset=0,blobSize=0,boundaryOffset=off)); continue
        if not (1<=w<=4096 and 1<=h<=4096): raise RuntimeError(f'TXTR page {i}: dimensoes invalidas {w}x{h}, blobOffset=0x{off:X}.')
        pages.append(dict(page=i, external=(off==0), width=w,height=h,blobOffset=off,blobSize=0,boundaryOffset=off))
    for i,p in enumerate(pages):
        off=p['blobOffset']
        if not off: continue
        nxt=None
        for q in pages[i+1:]:
            boundary=q.get('boundaryOffset', q['blobOffset'])
            if boundary:
                nxt=boundary; break
        stop=nxt if nxt is not None else end
        if stop <= off: raise RuntimeError(f'TXTR page {i}: blob range invalido.')
        p['blobSize']=stop-off
    return dict(count=count, chunkStart=start, chunkEnd=end, stride=stride, pages=pages)

def magic(ch): return VTC5 if int(ch)==3 else VTC1
def complete_magic(ch): return VTC6 if int(ch)==3 else VTC2

def write_r444(ch, page, raw_path, out):
    raw=Path(raw_path).read_bytes(); expected=page['width']*page['height']*2
    if len(raw)!=expected: raise RuntimeError(f"page_{page['page']:03d}: RGBA4444={len(raw)} bytes; esperado={expected}.")
    hdr=struct.pack('<IIIII', magic(ch), page['blobSize'], page['blobOffset'], page['width'], page['height'])
    out.parent.mkdir(parents=True,exist_ok=True); out.write_bytes(hdr+raw)
    validate_r444(ch,page,out)

def validate_r444(ch,page,path):
    b=path.read_bytes()
    if len(b)<20: raise RuntimeError(f'{path.name}: header menor que 20 bytes.')
    m,sz,off,w,h=struct.unpack_from('<IIIII',b,0); exp=20+page['width']*page['height']*2; bad=[]
    if m!=magic(ch): bad.append(f'magic 0x{m:08X}')
    if sz!=page['blobSize']: bad.append(f'sourceSize {sz}!={page["blobSize"]}')
    if off!=page['blobOffset']: bad.append(f'sourceOffset {off}!={page["blobOffset"]}')
    if (w,h)!=(page['width'],page['height']): bad.append(f'dims {w}x{h}')
    if len(b)!=exp: bad.append(f'filesize {len(b)}!={exp}')
    if bad: raise RuntimeError(f'{path.name}: R444 invalido: '+'; '.join(bad))

def write_complete(ch,count,path):
    path.write_bytes(struct.pack('<II', complete_magic(ch), count))
    m,c=struct.unpack('<II',path.read_bytes())
    if path.stat().st_size!=8 or m!=complete_magic(ch) or c!=count: raise RuntimeError('complete.vtc invalido.')

def normalize_pvr3_bc3_header(path):
    b=bytearray(path.read_bytes())
    if len(b)<52:
        raise RuntimeError(f'{path.name}: PVR menor que 52 bytes apos conversao.')

    ver=struct.unpack_from('<I',b,0)[0]
    pf=struct.unpack_from('<Q',b,8)[0]

    if ver!=PVR3_MAGIC:
        raise RuntimeError(f'{path.name}: PVRTexTool gerou magic PVR invalido 0x{ver:08X}.')
    if pf!=PVR_BC3:
        raise RuntimeError(f'{path.name}: PVRTexTool gerou pixelFormat {pf}, esperado 11 (BC3/DXT5).')

    # Normaliza apenas os campos do header exigidos pelo Runner.
    # O payload BC3 permanece intocado.
    struct.pack_into('<I',b,4,0)          # flags
    struct.pack_into('<I',b,16,PVR_SRGB) # colorSpace = sRGB
    struct.pack_into('<I',b,20,0)         # channelType
    struct.pack_into('<I',b,32,1)         # depth
    struct.pack_into('<I',b,36,1)         # numSurfaces
    struct.pack_into('<I',b,40,1)         # numFaces
    struct.pack_into('<I',b,44,1)         # numMipmaps

    path.write_bytes(b)

def make_bc3(png,out):
    out.parent.mkdir(parents=True,exist_ok=True); last=''
    for fmt in ('BC3','DXT5'):
        if out.exists():
            out.unlink()
        # Preserve the PNG's sRGB values in the BC3 payload. Using -ics sRGB
        # with plain -f BC3 selected PVRTexTool's default lRGB output and
        # applied an unwanted global gamma conversion before compression.
        encode_format=f'{fmt},{BC3_CHANNEL_TYPE},{BC3_OUTPUT_COLORSPACE}'
        cmd=[str(PVR),'-i',str(png),'-o',str(out),'-ics',BC3_INPUT_COLORSPACE,'-f',encode_format,'-m','1']
        r=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        if r.returncode==0 and out.is_file():
            normalize_pvr3_bc3_header(out)
            return
        last=r.stdout
    raise RuntimeError(f'PVRTexToolCLI falhou para {png.name}.\n{last}')

def validate_pvr(page,path):
    b=path.read_bytes()
    if len(b)<52: raise RuntimeError(f'{path.name}: PVR menor que 52 bytes.')
    vals=struct.unpack_from('<IIQIIIIIIIII',b,0)
    ver,flags,pf,cs,ct,h,w,depth,surfaces,faces,mips,meta=vals; payload=len(b)-(52+meta); expected=page['width']*page['height']; bad=[]
    if ver!=PVR3_MAGIC: bad.append(f'magic 0x{ver:08X}')
    if flags!=0: bad.append(f'flags {flags}')
    if pf!=PVR_BC3: bad.append(f'pixelFormat {pf}')
    if cs!=PVR_SRGB: bad.append(f'colorSpace {cs}')
    if ct!=0: bad.append(f'channelType {ct}')
    if (w,h)!=(page['width'],page['height']): bad.append(f'dims {w}x{h}')
    if depth!=1 or surfaces!=1 or faces!=1 or mips!=1: bad.append(f'depth/surfaces/faces/mips={depth}/{surfaces}/{faces}/{mips}')
    if 52+meta>len(b) or payload!=expected: bad.append(f'payload {payload}!={expected}')
    if bad: raise RuntimeError(f'{path.name}: PVR invalido: '+'; '.join(bad))

def validate_physical_cache_set(ch, tx, cache, pvr):
    """Reopen every output from disk before declaring the package complete.

    The old validation compared page IDs appended to in-memory lists. A later
    cleanup/copy step could therefore leave complete.vtc and the manifest
    claiming a complete set even when files were absent. The Vita would then
    regenerate those pages from data.win during chapter startup.
    """
    required = [p for p in tx['pages'] if p['blobOffset'] != 0]
    external = [p['page'] for p in tx['pages'] if p['blobOffset'] == 0]
    expected_names = {f"page_{p['page']:03d}" for p in required}
    actual_r444 = {p.stem for p in cache.glob('page_*.r444') if p.is_file()}
    actual_bc3 = {
        p.name[:-len('.bc3.pvr')]
        for p in pvr.glob('page_*.bc3.pvr') if p.is_file()
    }
    missing_r444 = sorted(expected_names - actual_r444)
    missing_bc3 = sorted(expected_names - actual_bc3)
    extra_r444 = sorted(actual_r444 - expected_names)
    extra_bc3 = sorted(actual_bc3 - expected_names)
    if missing_r444 or missing_bc3 or extra_r444 or extra_bc3:
        def sample(items): return ', '.join(items[:12]) + (' ...' if len(items) > 12 else '')
        problems = []
        if missing_r444: problems.append(f'R444 ausentes ({len(missing_r444)}): {sample(missing_r444)}')
        if missing_bc3: problems.append(f'BC3 ausentes ({len(missing_bc3)}): {sample(missing_bc3)}')
        if extra_r444: problems.append(f'R444 extras ({len(extra_r444)}): {sample(extra_r444)}')
        if extra_bc3: problems.append(f'BC3 extras ({len(extra_bc3)}): {sample(extra_bc3)}')
        raise RuntimeError('Conjunto fisico de caches incompleto: ' + '; '.join(problems))
    for page in required:
        base = f"page_{page['page']:03d}"
        validate_r444(ch, page, cache/f'{base}.r444')
        validate_pvr(page, pvr/f'{base}.bc3.pvr')
    return [p['page'] for p in required], external

def export_pages(source_win,work):
    work.mkdir(parents=True,exist_ok=True); env=os.environ.copy(); env['DELTARUNEVITA_PTC_EXPORT_DIR']=str(work.resolve())
    r=subprocess.run([str(UTMT),'load',str(source_win),'-s',str(CSX)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,env=env)
    print(r.stdout)
    if r.returncode!=0: raise RuntimeError('UndertaleModCLI falhou durante export de Texture Pages.')
    csvp=work/'pages.csv'
    if not csvp.is_file(): raise RuntimeError('pages.csv nao foi gerado.')
    with csvp.open('r',encoding='utf-8-sig',newline='') as f: return list(csv.DictReader(f))

def prepare_chapter(name,source_win):
    ch=int(name); label='chapter'+name; out=PREPARED_DIR/label; cache=out/'texture-cache'; pvr=out/'pvr'; work=PREPARED_DIR/'_work'/label
    if work.exists(): shutil.rmtree(work)
    if out.exists(): shutil.rmtree(out)
    work.mkdir(parents=True,exist_ok=True); cache.mkdir(parents=True,exist_ok=True); pvr.mkdir(parents=True,exist_ok=True); shutil.copy2(source_win,out/'data.win')
    print(f'[{label}] Parseando TXTR do data.win shipado...'); tx=parse_txtr(source_win); print(f"[{label}] TXTR: {tx['count']} pages | stride={tx['stride']}")
    print(f'\n[{label}] Exportando EmbeddedTextures...'); rows=export_pages(source_win,work); rows_by={int(r['page']):r for r in rows}
    if len(rows)!=tx['count']: raise RuntimeError(f"UTMT exportou {len(rows)} pages; TXTR possui {tx['count']}.")
    rids=[]; bids=[]; external=[]
    for n,page in enumerate(tx['pages'],1):
        pid=page['page']; base=f'page_{pid:03d}'
        if page['blobOffset']==0:
            external.append(pid); print(f'[{label}] {n:4d}/{tx["count"]:4d} {base} EXTERNAL -> skip'); continue
        row=rows_by.get(pid)
        if row is None: raise RuntimeError(f'{base}: ausente no export UTMT.')
        uw,uh=int(row['width']),int(row['height'])
        if (uw,uh)!=(page['width'],page['height']): raise RuntimeError(f'{base}: UTMT {uw}x{uh} diverge do TXTR {page["width"]}x{page["height"]}.')
        png=work/'png'/f'{base}.png'; raw=work/'rgba4444'/f'{base}.rgba4444'
        if not png.is_file() or not raw.is_file(): raise RuntimeError(f'{base}: arquivos exportados ausentes.')
        ro=cache/f'{base}.r444'; write_r444(ch,page,raw,ro); rids.append(pid)
        bo=pvr/f'{base}.bc3.pvr'; make_bc3(png,bo); validate_pvr(page,bo); bids.append(pid)
        opt='BC3' if page['width']==2048 and page['height']==2048 else 'R444'
        print(f'[{label}] {n:4d}/{tx["count"]:4d} {base} {page["width"]}x{page["height"]} blob=0x{page["blobOffset"]:X}+{page["blobSize"]} -> R444 + BC3 [OPT={opt}]')
    required=[p['page'] for p in tx['pages'] if p['blobOffset']!=0]
    if rids!=required or bids!=required: raise RuntimeError('Conjunto final de caches nao corresponde ao TXTR.')
    # Do not trust the lists above: reopen and validate the final physical tree.
    disk_ids, disk_external = validate_physical_cache_set(ch, tx, cache, pvr)
    if disk_ids != required or disk_external != external:
        raise RuntimeError('Auditoria fisica divergiu do TXTR.')
    # complete.vtc is deliberately the last cache file created. Its presence
    # now means the disk audit actually completed, rather than merely that the
    # generation loop once visited every page.
    write_complete(ch,tx['count'],cache/'complete.vtc')
    pages={str(p['page']):dict(width=p['width'],height=p['height'],blobOffset=p['blobOffset'],blobSize=p['blobSize'],external=(p['blobOffset']==0),optimized_format=(None if p['blobOffset']==0 else ('BC3' if p['width']==2048 and p['height']==2048 else 'R444'))) for p in tx['pages']}
    man=dict(tool_version=APP_VERSION,chapter=label,texture_pages=tx['count'],r444_pages=disk_ids,bc3_pages=disk_ids,external_pages=disk_external,bc3_encoding=dict(format='BC3/DXT5',channel_type=BC3_CHANNEL_TYPE,input_colorspace=BC3_INPUT_COLORSPACE,output_colorspace=BC3_OUTPUT_COLORSPACE,gamma_conversion=False),txtr=dict(entry_stride=tx['stride'],chunk_start=tx['chunkStart'],chunk_end=tx['chunkEnd']),magic=dict(r444=f'0x{magic(ch):08X}',complete=f'0x{complete_magic(ch):08X}'),pages=pages,validation=dict(r444='PHYSICAL_OK',bc3='PHYSICAL_OK_SRGB_PRESERVED',complete_vtc='WRITTEN_AFTER_PHYSICAL_AUDIT'))
    (out/'texture_manifest.json').write_text(json.dumps(man,indent=2),encoding='utf-8'); return man

def main():
    title('Preparar data.win + caches','R444 exato do Runner + BC3/PVR para todas as Texture Pages.')
    if not UTMT.is_file(): print('ERRO: source\\UTMT_CLI\\UndertaleModCli.exe ausente.'); return 1
    if not PVR.is_file(): print('ERRO: source\\PVRTexToolCLI\\PVRTexToolCLI.exe ausente.'); return 1
    chapters=discover_chapters()
    if not chapters: print('Nenhum chapters\\<N>\\data.win encontrado.'); return 1
    print('Capitulos:'); [print(f'  {n}: {rel(w)}') for n,w in chapters]
    if input('\nPreparar todos os capitulos acima? [Y/N]: ').strip().lower() not in ('y','yes','s','sim'): print('Cancelado.'); return 0
    if PREPARED_DIR.exists(): shutil.rmtree(PREPARED_DIR)
    PREPARED_DIR.mkdir(parents=True,exist_ok=True); mans=[]
    try:
        for n,w in chapters: title(f'Preparando Chapter {n}',rel(w)); mans.append(prepare_chapter(n,w))
    except Exception as e:
        print('\n'+'='*WIDTH+'\n PREPARACAO FALHOU\n'+'='*WIDTH+'\n\n'+str(e)+'\n\nNenhum data.win de entrada foi modificado.'); return 1
    (PREPARED_DIR/'prepared_manifest.json').write_text(json.dumps(dict(tool_version=APP_VERSION,chapters=mans),indent=2),encoding='utf-8')
    title('Concluido','Pacote preparado e validado para transferencia.'); print('Resultado:\n  prepared\\\n')
    for m in mans: print(f"  {m['chapter']}: {m['texture_pages']} TXTR pages | {len(m['r444_pages'])} R444 | {len(m['bc3_pages'])} BC3 | {len(m['external_pages'])} external")
    print('\nEstrutura:\n  prepared\\chapterN\\data.win\n  prepared\\chapterN\\texture-cache\\page_NNN.r444\n  prepared\\chapterN\\texture-cache\\complete.vtc\n  prepared\\chapterN\\pvr\\page_NNN.bc3.pvr\n'); input('Pressione ENTER para encerrar...'); return 0

if __name__=='__main__': sys.exit(main())
