"""Generate the app's original offline driving-demo video and poster.

Only Pillow and an FFmpeg executable are needed. All artwork is drawn here,
without external images or copyrighted game material. Webcam crop in the
1280x720 source: x=32, y=432, width=352, height=259.
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import math
import random
import subprocess
import shutil

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "public"
OUT.mkdir(exist_ok=True)
W, H = 1280, 720
S = 2


def font(size, bold=False):
    names = ["C:/Windows/Fonts/seguisb.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    for name in names:
        if Path(name).exists():
            return ImageFont.truetype(name, round(size*S))
    return ImageFont.load_default()


def line(d, points, color, width=1):
    d.line([(round(x*S), round(y*S)) for x,y in points], fill=color, width=round(width*S))


def poly(d, points, color):
    d.polygon([(round(x*S), round(y*S)) for x,y in points], fill=color)


def rect(d, box, color, radius=0, outline=None, width=1):
    box = tuple(round(v*S) for v in box)
    if radius:
        d.rounded_rectangle(box, radius=round(radius*S), fill=color, outline=outline, width=round(width*S))
    else:
        d.rectangle(box, fill=color, outline=outline, width=round(width*S))


def ell(d, box, color):
    d.ellipse(tuple(round(v*S) for v in box), fill=color)


def text(d, xy, value, size, color, bold=False):
    d.text(tuple(round(v*S) for v in xy), value, font=font(size,bold), fill=color)


def background():
    im = Image.new("RGB", (W*S,H*S))
    d = ImageDraw.Draw(im)
    stops = [(0,(13,16,45)),(.28,(58,38,93)),(.52,(168,77,111)),(.67,(34,31,69)),(1,(9,13,34))]
    for y in range(H*S):
        p=y/(H*S)
        for (a,ca),(b,cb) in zip(stops,stops[1:]):
            if a<=p<=b:
                t=(p-a)/(b-a)
                c=tuple(round(ca[i]*(1-t)+cb[i]*t) for i in range(3))
                d.line((0,y,W*S,y),fill=c)
                break
    rng=random.Random(7)
    for _ in range(85):
        x,y=rng.randrange(W),rng.randrange(10,250)
        r=rng.choice([.5,.5,1])
        ell(d,(x-r,y-r,x+r,y+r),(133,133,181))
    # Sunset in the distant pass, atmospheric clouds and mountains.
    glow=Image.new("RGBA",im.size)
    gd=ImageDraw.Draw(glow)
    ell(gd,(630,145,950,465),(255,165,137,42))
    glow=glow.filter(ImageFilter.GaussianBlur(45*S))
    im=Image.alpha_composite(im.convert("RGBA"),glow)
    d=ImageDraw.Draw(im)
    ell(d,(719,213,863,357),(251,176,142))
    for i in range(5):
        y=302+i*12
        rect(d,(717,y,866,y+3+i),(139,76,117))
    poly(d,[(0,283),(61,266),(117,286),(170,241),(240,265),(309,228),(385,283),(467,265),(550,300),(631,288),(701,325),(789,330),(869,291),(941,269),(1014,284),(1060,244),(1128,251),(1185,204),(1280,248),(1280,464),(0,464)],(60,43,92))
    poly(d,[(0,365),(61,326),(132,353),(188,288),(262,324),(308,306),(380,369),(443,342),(505,372),(574,354),(655,386),(729,378),(815,389),(902,349),(969,314),(1012,330),(1088,286),(1142,318),(1210,285),(1280,314),(1280,499),(0,499)],(31,32,66))
    poly(d,[(0,414),(112,386),(227,425),(311,382),(416,426),(509,414),(626,441),(756,392),(870,425),(994,388),(1132,418),(1280,376),(1280,720),(0,720)],(18,27,47))
    # Sparse futuristic architecture on the distant horizon.
    for x,y,w,h in [(375,369,16,44),(401,361,8,52),(425,382,20,31),(929,352,12,69),(951,378,20,44),(979,349,8,75),(1005,364,25,63)]:
        rect(d,(x,y,x+w,y+h),(24,28,57))
        line(d,[(x+2,y+8),(x+w-2,y+8)],(100,89,160),1)
    # Road curves toward the sun; ribbons at either edge catch violet light.
    poly(d,[(736,393),(784,393),(913,439),(1090,502),(1280,569),(1280,720),(198,720),(393,583),(585,470)],(13,19,35))
    poly(d,[(736,393),(748,393),(610,472),(422,598),(262,720),(198,720),(393,583),(585,470)],(32,42,65))
    poly(d,[(781,393),(789,395),(925,439),(1107,503),(1280,557),(1280,575),(1090,517),(910,451)],(42,43,69))
    line(d,[(736,394),(590,470),(402,590),(216,720)],(92,113,150),2)
    line(d,[(782,394),(916,444),(1102,510),(1280,568)],(180,108,159),2)
    line(d,[(733,399),(582,481),(390,605),(233,720)],(111,88,212),3)
    # Hillside grasses and a few silhouetted pines.
    for x,y,scale in [(93,386,1),(124,399,.65),(1177,366,1),(1211,378,.8),(1064,412,.45),(358,417,.4)]:
        poly(d,[(x,y-64*scale),(x-19*scale,y-15*scale),(x-8*scale,y-15*scale),(x-29*scale,y+12*scale),(x+29*scale,y+12*scale),(x+8*scale,y-15*scale),(x+19*scale,y-15*scale)],(12,24,42))
        rect(d,(x-2,y,x+2,y+28*scale),(12,24,42))
    # Ambient streaks on the asphalt.
    for points in [[(687,459),(581,609)],[(884,500),(1042,720)],[(781,462),(787,660)]]:
        line(d,points,(20,29,49),1)
    return im


def car_overlay():
    im=Image.new("RGBA",(W*S,H*S))
    d=ImageDraw.Draw(im)
    # A low poly, original coupe: strong readable rear silhouette.
    ell(d,(600,578,1030,658),(3,8,19,170))
    glow=Image.new("RGBA",im.size)
    gd=ImageDraw.Draw(glow)
    ell(gd,(633,610,1004,636),(34,208,204,70))
    glow=glow.filter(ImageFilter.GaussianBlur(18*S))
    im=Image.alpha_composite(im,glow)
    d=ImageDraw.Draw(im)
    poly(d,[(623,558),(661,538),(699,562),(693,630),(662,638),(636,618)],(5,12,22))
    poly(d,[(956,546),(996,538),(1020,566),(1012,614),(982,624),(957,606)],(5,12,22))
    poly(d,[(636,540),(686,490),(747,467),(867,471),(949,500),(1009,545),(1006,603),(957,627),(681,631),(632,601)],(18,102,113))
    poly(d,[(636,540),(686,490),(748,467),(868,472),(949,500),(995,541),(924,561),(698,561)],(30,157,164))
    poly(d,[(681,500),(736,477),(859,482),(920,506),(947,546),(697,545)],(10,39,60))
    poly(d,[(737,483),(850,486),(906,506),(916,530),(709,530)],(15,56,76))
    poly(d,[(745,483),(772,483),(746,529),(717,529)],(48,88,106))
    line(d,[(688,503),(739,479),(860,485),(917,508)],(88,221,214),2)
    poly(d,[(644,544),(700,554),(930,551),(995,541),(1004,563),(960,583),(676,588),(635,565)],(29,179,180))
    poly(d,[(637,569),(676,590),(960,584),(1007,564),(1006,601),(958,624),(682,629),(634,599)],(18,106,119))
    poly(d,[(681,593),(952,588),(982,603),(951,618),(687,621),(655,603)],(5,25,41))
    # Red continuous rear lamp and fine white daylight trim.
    line(d,[(647,566),(685,578),(952,573),(991,557)],(255,92,125),5)
    line(d,[(649,565),(686,577),(951,572),(991,556)],(255,192,194),1)
    line(d,[(648,540),(691,550),(929,548),(991,539)],(106,246,225),2)
    # Spoiler and supports.
    poly(d,[(696,548),(705,547),(703,568),(695,568)],(9,31,45))
    poly(d,[(925,543),(933,543),(939,562),(931,562)],(9,31,45))
    poly(d,[(653,537),(973,531),(989,539),(665,549)],(7,30,45))
    line(d,[(654,537),(973,531),(987,538)],(78,191,192),2)
    rect(d,(793,595,852,610),(161,205,211),2)
    text(d,(800,592),"NOVA",10,(22,52,69),True)
    for x in (684,931):
        ell(d,(x,602,x+24,614),(7,11,21))
        ell(d,(x+4,604,x+20,610),(62,79,93))
    return im


def webcam():
    im=Image.new("RGBA",(W*S,H*S))
    d=ImageDraw.Draw(im)
    # Outer box is the exact crop offered by the app's demo profile.
    rect(d,(32,432,384,691),(23,15,44),10)
    rect(d,(35,435,381,688),(32,22,57),8)
    # Purple studio wall, geometric acoustic panels and warm shelf lighting.
    for x in [50,99,148,272,321]:
        rect(d,(x,450,x+35,540),(39,28,68),3)
        line(d,[(x+4,456),(x+30,456)],(54,39,88),1)
    rect(d,(53,548,138,552),(103,72,156),1)
    rect(d,(61,526,72,547),(61,146,138),2)
    poly(d,[(65,525),(48,514),(64,517),(59,501),(70,513),(83,506),(76,523)],(65,159,142))
    rect(d,(89,530,100,547),(215,131,85),2)
    rect(d,(103,522,111,547),(106,83,163),1)
    line(d,[(353,448),(353,642)],(138,71,248),4)
    line(d,[(358,449),(358,643)],(76,43,122),4)
    # Chair behind the subject.
    rect(d,(144,494,285,678),(12,17,32),33)
    line(d,[(155,515),(157,622)],(57,49,88),4)
    line(d,[(273,515),(278,621)],(79,50,122),4)
    # Hoodie and neck.
    poly(d,[(94,688),(112,628),(157,605),(180,599),(244,598),(272,608),(313,636),(325,688)],(20,25,47))
    poly(d,[(161,609),(182,598),(245,599),(264,612),(246,652),(204,663),(167,638)],(34,37,64))
    poly(d,[(184,579),(238,578),(241,613),(216,630),(186,610)],(177,109,97))
    poly(d,[(185,592),(213,602),(237,590),(238,607),(216,620),(186,606)],(145,79,83))
    # Ears and face, naturally warm against violet light.
    ell(d,(162,523,181,561),(186,116,104))
    ell(d,(240,521,259,558),(177,102,102))
    poly(d,[(175,501),(192,485),(224,484),(246,504),(248,548),(238,579),(219,594),(204,595),(183,579),(172,549)],(213,144,119))
    poly(d,[(233,503),(246,508),(247,550),(236,581),(218,593),(224,572),(233,548)],(181,111,111))
    poly(d,[(180,513),(180,549),(193,571),(209,577),(223,569),(230,550),(229,511)],(221,151,121))
    # Hair silhouette and swept shapes.
    poly(d,[(171,530),(164,505),(175,478),(191,473),(197,465),(228,470),(247,485),(254,506),(247,533),(237,512),(218,501),(190,514),(179,511)],(20,19,33))
    poly(d,[(177,492),(193,479),(224,479),(238,490),(208,487),(186,500)],(48,37,54))
    line(d,[(182,503),(210,490),(237,497)],(72,45,76),3)
    # Eyes, nose, brows and a slight smile.
    line(d,[(185,529),(198,525)],(48,31,35),3)
    line(d,[(219,526),(232,528)],(48,31,35),3)
    ell(d,(190,534,196,538),(25,29,38))
    ell(d,(222,533,228,537),(25,29,38))
    line(d,[(210,536),(207,552),(215,554)],(174,103,91),2)
    line(d,[(199,566),(209,569),(222,565)],(106,65,67),2)
    # Headset band, cups and soft highlights.
    d.arc((158*S,470*S,262*S,573*S),180,360,fill=(15,20,34),width=11*S)
    d.arc((158*S,470*S,262*S,573*S),185,355,fill=(114,82,171),width=3*S)
    rect(d,(158,516,175,562),(9,15,28),8)
    rect(d,(161,521,169,554),(135,93,215),4)
    rect(d,(246,513,263,560),(9,15,28),8)
    rect(d,(252,519,260,554),(129,80,215),4)
    line(d,[(256,553),(248,575),(230,579)],(41,40,61),3)
    ell(d,(224,576,235,582),(12,20,31))
    # Hoodie folds, zipper and microphone arm entering from the right.
    line(d,[(168,636),(154,677)],(45,49,76),2)
    line(d,[(246,644),(263,684)],(45,49,76),2)
    line(d,[(215,633),(215,688)],(72,72,101),1)
    line(d,[(186,638),(181,664)],(115,115,137),2)
    line(d,[(241,640),(246,666)],(115,115,137),2)
    line(d,[(381,671),(326,623),(278,634)],(10,15,27),9)
    line(d,[(380,663),(327,614),(281,626)],(81,67,108),2)
    rect(d,(269,606,289,650),(11,17,29),8)
    for y in range(612,643,5):
        line(d,[(273,y),(284,y)],(58,58,81),1)
    # Small live tag and studio crop border.
    rect(d,(45,444,96,464),(24,20,44),5)
    ell(d,(53,451,58,456),(248,97,143))
    text(d,(63,446),"LIVE",9,(238,222,247),True)
    rect(d,(32,432,384,691),None,10,outline=(115,89,154),width=1)
    return im


def hud():
    im=Image.new("RGBA",(W*S,H*S))
    d=ImageDraw.Draw(im)
    text(d,(43,30),"NOVA",24,(241,238,254),True)
    text(d,(45,62),"NIGHT DRIVE",9,(175,159,201),True)
    rect(d,(43,94,47,125),(121,240,217),2)
    text(d,(60,90),"SUNSET RUN",12,(236,231,252),True)
    text(d,(60,109),"Coastal highway · Free roam",10,(160,152,185))
    text(d,(1120,32),"01",27,(236,236,253),True)
    text(d,(1164,45),"/ 08",13,(151,145,175))
    text(d,(1124,73),"POSITION",8,(165,152,183),True)
    rect(d,(1069,608,1239,681),(13,18,35,180),12)
    text(d,(1085,620),"6",16,(109,238,215),True)
    text(d,(1106,618),"184",34,(245,245,254),True)
    text(d,(1182,642),"KM/H",9,(160,166,189),True)
    rect(d,(1086,665,1221,668),(46,49,70),1)
    rect(d,(1086,665,1180,668),(99,231,210),1)
    text(d,(1110,695),"ORIGINAL DEMO",8,(112,116,147))
    # Clean route map between top right and lower HUD.
    line(d,[(1182,122),(1169,141),(1190,163),(1160,183),(1168,206)],(102,96,128),2)
    ell(d,(1164,199,1173,208),(105,238,216))
    return im


def road_marks(im,t):
    d=ImageDraw.Draw(im)
    # Perspective-aware dashes move toward the viewer across 12 seconds.
    for lane in [.34,.68]:
        for i in range(10):
            q=((i/10+t*.45)%1)
            q2=min(1,q+.034+.025*q)
            points=[]
            for p,side in [(q,-1),(q,1),(q2,1),(q2,-1)]:
                depth=p*p
                y=403+350*depth
                left=731-538*depth
                right=789+645*depth
                x=left+(right-left)*lane
                half=(.5+4.5*depth)*side
                points.append((x+half,y))
            poly(d,points,(91,92,119))
    # Subtle passing shoulder reflectors reinforce forward motion.
    for i in range(7):
        q=(i/7+t*.36)%1
        p=q*q
        x=731-598*p
        y=401+360*p
        line(d,[(x,y),(x,y-3-20*p)],(80,84,113),1+2*p)
        line(d,[(x,y-3-20*p),(x,y-1-14*p)],(143,221,219),1+2*p)


def make():
    ffmpeg=shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("FFmpeg is required")
    base=background()
    car=car_overlay()
    camera=webcam()
    interface=hud()
    frames=360
    cmd=[ffmpeg,"-hide_banner","-loglevel","error","-y","-f","rawvideo","-vcodec","rawvideo",
         "-pix_fmt","rgb24","-s",f"{W}x{H}","-r","30","-i","-",
         "-f","lavfi","-i","sine=frequency=65:sample_rate=44100:duration=12",
         "-af","volume=0.035","-c:v","libx264","-preset","fast","-crf","22",
         "-pix_fmt","yuv420p","-c:a","aac","-b:a","96k","-t","12","-movflags","+faststart",str(OUT/"demo.mp4")]
    process=subprocess.Popen(cmd,stdin=subprocess.PIPE)
    for i in range(frames):
        im=base.copy()
        road_marks(im,i/30)
        # Car has a restrained lateral sway, while the camera remains stable.
        shifted=Image.new("RGBA",im.size)
        shifted.paste(car,(round(math.sin(i/30*1.4)*2*S),round(math.sin(i/30*3)*.6*S)))
        im=Image.alpha_composite(im,shifted)
        im=Image.alpha_composite(im,camera)
        im=Image.alpha_composite(im,interface)
        frame=im.convert("RGB").resize((W,H),Image.Resampling.LANCZOS)
        if i==0:
            frame.save(OUT/"demo-poster.jpg",quality=95,subsampling=0)
        process.stdin.write(frame.tobytes())
    process.stdin.close()
    if process.wait():
        raise SystemExit("FFmpeg demo generation failed")
    (OUT/"favicon.svg").write_text('''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="18" fill="#11111a"/><rect x="16" y="12" width="32" height="40" rx="8" fill="none" stroke="#a697ff" stroke-width="5"/><path d="M23 27h18M23 35h18" stroke="#d8d0ff" stroke-width="4" stroke-linecap="round"/></svg>''',encoding="utf-8")
    print(f"Created {OUT/'demo.mp4'} (1280×720, 12s, 30fps), poster and favicon.")


if __name__=="__main__":
    make()
