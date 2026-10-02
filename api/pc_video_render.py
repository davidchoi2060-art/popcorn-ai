"""Approved v7 photo edit: actual snapshot text, five shots, no invented 3D."""
import json
import subprocess
from pathlib import Path
from PIL import ImageFont
from imageio_ffmpeg import get_ffmpeg_exe

ASSETS=Path(__file__).resolve().parents[1]/'assets'/'pc-video'
VERSION='pc-ad-v7.1'
DURATION=10
TRACKS=json.loads((ASSETS/'music'/'licenses.json').read_text(encoding='utf-8'))['tracks']
MUSIC={t['id']:dict(t,file=ASSETS/'music'/(t['id']+'.m4a')) for t in TRACKS}
FONT=ASSETS/'fonts'/'NotoSansCJKkr-Regular.otf'

def ready():
    try:
        return FONT.is_file() and all(t['file'].is_file() for t in MUSIC.values()) and bool(get_ffmpeg_exe())
    except Exception:return False

def safe(value):
    # Product data is text, never ASS overrides or ffmpeg filter syntax.
    return ''.join(c for c in str(value) if c not in '{}\\' and ord(c)>=32)[:200]

def lines(value,size,width=960,max_lines=2):
    text=safe(value);font=ImageFont.truetype(str(FONT),size)
    result=[];line=''
    for char in text:
        if font.getlength(line+char)*.8>width and line:
            result.append(line.rstrip());line=''
        line+=char
    if line:result.append(line.rstrip())
    if len(result)>max_lines:
        return lines(value,max(32,int(size*.9)),width,max_lines) if size>32 else ('…',32)
    return r'\N'.join(result),size

def subtitles(s):
    f=s['facts'];cpu=f.get('cpu') or 'CPU 구성';gpu=f.get('gpu') or '그래픽 구성'
    ram=f.get('ram_gb');storage=f.get('storage_gb')
    ram=f'{ram:g}GB 메모리' if isinstance(ram,(int,float)) else '메모리 구성 확인'
    storage=(f'SSD {storage/1000:g}TB' if storage>=1000 else f'SSD {storage:g}GB') if isinstance(storage,(int,float)) else '저장장치 구성 확인'
    styles='''[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Heading,Noto Sans CJK KR,116,&H003A4330,&H003A4330,&H00FFFFFF,&H00FFFFFF,-1,0,0,0,80,100,0,0,1,5,0,7,0,0,0,1
Style: Big,Noto Sans CJK KR,170,&H003F4800,&H003F4800,&H00FFFFFF,&H00FFFFFF,-1,0,0,0,80,100,0,0,1,5,0,7,0,0,0,1
Style: Body,Noto Sans CJK KR,87,&H003A4330,&H003A4330,&H00FFFFFF,&H00FFFFFF,0,0,0,0,80,100,0,0,1,5,0,7,0,0,0,1
Style: Label,Noto Sans CJK KR,34,&H004B5540,&H004B5540,&H00FFFFFF,&H00FFFFFF,-1,0,0,0,80,100,3,0,1,5,0,7,0,0,0,1
Style: Note,Noto Sans CJK KR,28,&H00556050,&H00556050,&H00FFFFFF,&H00FFFFFF,0,0,0,0,80,100,0,0,1,5,0,7,0,0,0,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    events=[]
    def put(a,b,style,x,y,value,size,max_lines=2):
        txt,actual=lines(value,size,max_lines=max_lines)
        events.append(f'Dialogue: 0,{a},{b},{style},,0,0,0,,{{\\move({x-35},{y},{x},{y},0,160)\\fad(80,70)\\fs{actual}}}{txt}\n')
    put('0:00:00.00','0:00:01.00','Label',80,170,'POPCORN PC / '+s['configuration_id'],34)
    put('0:00:00.00','0:00:01.00','Heading',80,300,'나에게 맞는 한 대',116)
    put('0:00:01.00','0:00:03.50','Label',900,170,'01 / GRAPHICS',34)
    put('0:00:01.00','0:00:03.50','Big',900,320,gpu,170)
    put('0:00:01.18','0:00:03.50','Body',900,670,'화면과 그래픽 처리',87)
    put('0:00:03.50','0:00:05.50','Label',80,170,'02 / PROCESSOR',34)
    put('0:00:03.50','0:00:05.50','Big',80,320,cpu,170)
    put('0:00:03.65','0:00:05.50','Body',80,670,'프로그램의 연산 처리',87)
    put('0:00:05.50','0:00:07.50','Label',900,170,'03 / MEMORY & STORAGE',34)
    put('0:00:05.50','0:00:07.50','Heading',900,300,ram,116)
    put('0:00:05.65','0:00:07.50','Heading',900,470,storage,116)
    put('0:00:05.70','0:00:07.50','Body',900,660,'작업 데이터와 파일 보관',87)
    put('0:00:07.50','0:00:10.00','Label',80,150,s['configuration_id']+' / 구성 한눈에 보기',34)
    put('0:00:07.50','0:00:10.00','Heading',80,260,s['title'],116)
    put('0:00:07.65','0:00:10.00','Body',80,670,ram+' · '+storage,87)
    put('0:00:07.65','0:00:10.00','Body',80,810,s['cooling'],87)
    put('0:00:00.00','0:00:10.00','Note',80,1012,'AI 조립 예시 · 실제 외형과 성능은 제품·사용 조건에 따라 다름',28)
    return styles+''.join(events)

def render(s,raw,directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    (directory/'source.png').write_bytes(raw)
    (directory/'text.ass').write_text(subtitles(s),encoding='utf-8')
    ff=get_ffmpeg_exe()
    def run(args):
        subprocess.run([ff,'-hide_banner','-loglevel','error','-y',*args],cwd=directory,check=True,timeout=240,capture_output=True)
    # Crop normalized to the source: same five shots as v7, no new angles.
    shots=[(1,'',False,'1.0+0.12*min(on/12,1)'),(2.5,'crop=680:820:155:210,',True,'1.0+0.07*min(on/10,1)'),(2,'crop=650:660:150:170,',False,'1.08-0.08*min(on/12,1)'),(2,'',True,'1.0+0.06*min(on/10,1)'),(2.5,'',False,'1.10-0.10*min(on/14,1)')]
    for i,(duration,crop,left,zoom) in enumerate(shots):
        vf='scale=1024:1024,'+crop+'scale=1800:1800:force_original_aspect_ratio=decrease,pad=2200:2160:(ow-iw)/2:(oh-ih)/2:white,'
        vf+=f"zoompan=z='{zoom}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s=1240x1240:fps=30,crop=1240:1080:0:80,pad=1920:1080:{0 if left else 680}:0:white"
        run(['-loop','1','-framerate','30','-i','source.png','-vf',vf,'-t',str(duration),'-an','-c:v','libx264','-threads','2','-preset','veryfast','-crf','20','-pix_fmt','yuv420p',f'shot-{i}.mp4'])
    (directory/'concat.txt').write_text(''.join(f"file 'shot-{i}.mp4'\n" for i in range(5)),encoding='utf-8')
    run(['-f','concat','-safe','0','-i','concat.txt','-c','copy','picture.mp4'])
    # Paths in filters are fixed local relative names, never caller input.
    import shutil
    shutil.copyfile(FONT,directory/'font.otf')
    args=['-i','picture.mp4']
    if s['music']!='none':args+=['-i',str(MUSIC[s['music']]['file'])]
    args+=['-vf','ass=text.ass:fontsdir=.','-t','10','-c:v','libx264','-threads','2','-preset','veryfast','-crf','20','-pix_fmt','yuv420p']
    if s['music']!='none':args+=['-af','afade=t=in:st=0:d=0.1,afade=t=out:st=9.5:d=0.5','-c:a','aac','-b:a','192k']
    else:args+=['-an']
    run([*args,'-movflags','+faststart','intro.mp4'])
    run(['-ss','0.5','-i','intro.mp4','-frames:v','1','thumb.jpg'])
    run(['-i','intro.mp4','-f','null','-'])
    if (directory/'intro.mp4').stat().st_size>30*1024*1024:raise ValueError('Video too large')
    return directory/'intro.mp4',directory/'thumb.jpg'
