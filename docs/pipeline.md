# 传奇一瞬 1.0 算法规格（由 classes3.dex 反编译还原）

本文件是 Linux 移植的唯一算法依据。所有常量、运算顺序与边界行为均来自 jadx 反编译的
`decompiled/app/sources/xyz/shuncongci/leica/`。Android 特有的解码/编码差异单独标注。

## 1. 数据类型

- `Planes`：三张 `uint8` 平面 `(H, W)`，`p0=R, p1=G, p2=B`；忽略 alpha。
- `Frame`：`float32` CHW，形状 `(C, H, W)`；`C=1` 或 `3`。
- 图像坐标：行优先，`y*W+x`；EXIF 方向在解码后统一应用。
- 色彩：所有 `Planes` 为 sRGB 8-bit；`Frame` 多数为 `[0,1]`，defocus 为 `[-1,1]`。

## 2. 常量与枚举

```text
LeicaSizes:
  MODEL_SHORT_EDGE = 1024
  WORK_MAX_SIDE    = 2048
  PREVIEW_MAX_SIDE = 1280
  COLOR_MAX_PIXELS = 12_500_000

BokehOutput:
  ORIGINAL   label="原图直出",     longEdge=null
  SIZE_2048  label="降低至2048出图", longEdge=2048
  SIZE_1024  label="降低至1024出图", longEdge=1024

ProcessingMode:
  COLOR_ONLY      label="仅调色",   color=true,  blur=false
  BLUR_ONLY       label="仅虚化",   color=false, blur=true
  COLOR_AND_BLUR  label="调色＋虚化", color=true,  blur=true

LegendaryMath.apertures = [0.95, 1.8, 2.0, 2.8, 4.0, 5.6]
gain(aperture):
  0.95 -> 53.333336
  1.8  -> 21.6
  2.0  -> 19.44
  2.8  -> 15.12
  4.0  -> 10.8
  5.6  -> 7.714286
  其他 -> 抛错 "不支持的光圈"

Fusion.SIGMA_L  = 25.0  (L 通道)
Fusion.SIGMA_AB = 20.0  (a/b 通道)
```

## 3. 尺寸计算（LeicaSizes.kt）

```text
colorSize(w,h):
  px=w*h
  if px <= 12_500_000: return (w,h)
  s=sqrt(12_500_000/px); w'=max(1,int(w*s)); h'=max(1,int(h*s))
  while w'*h' > 12_500_000:
     if w'>=h': w'-- else h'--
  return (w',h')

colorSample(w,h):
  (tw,th)=colorSize(w,h); sample=1
  while w/(2*sample) >= tw and h/(2*sample) >= th: sample*=2
  return sample

workingSize(w,h,output):
  if output.longEdge == null: return (w,h)
  e=longEdge; m=max(w,h)
  fitted(n) = max(1, (n*e + m/2) / m)   // 整数除法
  return (fitted(w), fitted(h))

processingSize(w,h,blurEnabled,output):
  return blurEnabled ? workingSize(w,h,output) : colorSize(w,h)

modelSize(w,h,blurEnabled,output):     // blurEnabled/output 未使用
  newLong = int( max(w,h) * 1024 / min(w,h) )   // double 除法后截断
  return w<=h ? (1024,newLong) : (newLong,1024)

ganSample(w,h):
  sample=1
  while (min(w,h)/sample)/2 >= 1024: sample*=2
  return sample

workingSample(w,h,output):
  if output.longEdge==null: return 1
  e=longEdge; sample=1
  while (max(w,h)/sample)/2 >= e: sample*=2
  return sample

depthSize(w,h):
  desired = 518.0 / min(w,h)
  factor  = min(desired, 2044.0 / max(w,h))
  dim(n)  = clamp( int(rint(n*factor/14))*14, 14, 2044 )
  return (dim(w), dim(h))

previewSize(w,h,maxSide=1280):
  if max(w,h)<=maxSide: return (w,h)
  s=maxSide/max(w,h); return (max(1,int(w*s)), max(1,int(h*s)))
```

## 4. 解码与 EXIF

App 使用 `BitmapFactory`（`inSampleSize` 为 2 的幂）解码，然后 `Planes.setFromArgbRows`：
`p0=(c>>16)&255, p1=(c>>8)&255, p2=c&255`（忽略 alpha）。

`Planes.exifTransposed(orientation)`（2..8；1 原样）：

| orientation | 源坐标 (sx,sy) |
|---|---|
| 2 | (w-1-x, y) |
| 3 | (w-1-x, h-1-y) |
| 4 | (x, h-1-y) |
| 5 | (y, x) |
| 6 | (y, h-1-x) |
| 7 | (w-1-y, h-1-x) |
| 8 | (w-1-y, x) |

Linux 移植用 Pillow 解码并 `ImageOps.exif_transpose`；不模拟 `inSampleSize`（直接全量解码后
用同一套自定义重采样），这是与 App 唯一有意的像素来源差异。

### 三条解码路径

```text
decodeOriginal(uri):
  (ow,oh)=EXIF 后的源尺寸
  (tw,th)=colorSize(ow,oh)
  bmp=decode(uri, colorSample(sw,sh)); planes=fromArgb; planes=exifTransposed(orientation)
  out = (size==(tw,th)) ? planes : Resample.resize(planes,tw,th,BICUBIC)
  downscaled = (tw,th)!=(ow,oh)

decodeWorking(uri, output):
  (tw,th)=workingSize(ow,oh,output)
  bmp=decode(uri, workingSample(sw,sh,output)); planes=fromArgb; exifTransposed
  out=Resample.resize(planes,tw,th,BICUBIC)
  downscaled = output.longEdge!=null && max(sw,sh)>longEdge

decodeGanInput(uri):
  (mw,mh)=modelSize(ow,oh)
  bmp=decode(uri, ganSample(sw,sh)); planes=fromArgb; exifTransposed
  out=Resample.resize(planes,mw,mh,BILINEAR)
```

## 5. 自定义重采样（Resample.kt）

`PRECISION_BITS=22`，定点 `1.0 = 4194304`，累加初值 `2097152`（0.5 ulp）。

滤波器权重（`x=abs(v)`）：

```text
BILINEAR (support=1): x<1 ? 1-x : 0
BICUBIC  (support=2, a=-0.5):
  x<1: ((1.5x - 2.5)*x*x) + 1
  x<2: ((((x-5)*x+8)*x)-4) * -0.5
  else 0
LANCZOS  (support=3):
  x==0 ? 1
  x<3 ? sin(pi x)*sin(pi x/3) / ((pi^2 x^2)/3)
  else 0
```

`coeffs(inSize,outSize,filter)`：

```text
scale=in/out; filterScale=max(scale,1); support=filter.support*filterScale
ksize=ceil(support)*2+1
for xx in 0..out-1:
  center=(xx+0.5)*scale
  xmin=max(0, int(center-support+0.5))
  xmax=min(in, int(center+support+0.5))
  n=xmax-xmin
  w[i]=weight((xmin+i-center+0.5)*(1/filterScale)), i<n
  ww=sum(w); w[i]/=ww (若 ww==0 则不变)
  kk[xx*ksize+i] = round_half_away(w[i]*4194304)
  bounds[xx]=(xmin,n)
```

`horizontal` / `vertical`：

```text
ss = 2097152
for i in 0..n-1: ss += pixel * kk[xx*ksize+i]     // int32
out = clip8(ss)
clip8(v): v<=0 -> 0; else s=v>>22; min(s,255)
```

`resize`: 先水平（若宽度变化）再垂直（若高度变化）；尺寸不变则复制 Planes。

## 6. 高斯模糊（Gaussian.kt）

```text
kernel(sigma):
  n = (round(8*sigma+1) | 1)          // 奇数
  d[i]=exp(-0.5 * ((i-(n-1)/2)/sigma)^2); normalize
blur(data,w,h,sigma):
  水平：每行用 reflect101 边界，卷积核 k
  垂直：按 16 列条带，reflect101 边界，卷积核 k
  reflect101(i,n): n==1 ->0; 否则按 -i / 2n-2-i 反复折叠
```

移植用 `cv2.sepFilter2D(..., borderType=BORDER_REFLECT_101)`，float32，核与上式完全一致。

## 7. Lab 色彩（Lab.kt / LabFusion.kt）

```text
toLinear[256]: x=i/255; x<=0.04045 ? x/12.92 : ((x+0.055)/1.055)^2.4
srgbTab[256]: clamp(round(toLinear[i]*2040),0,65535)

cbrtTab[3072]:
  x=i*(1/2040)
  v = x<0.008856 ? 7.787x+0.13793103448275862 : cbrt(x)
  clamp(round(32768*v),0,65535)

coeffs[9]:
  m = [0.412453,0.35758,0.180423,
       0.212671,0.71516,0.072169,
       0.019334,0.119193,0.950227]
  wp= [0.950456,1.0,1.088754]
  coeffs[i]=round(4096*m[i]/wp[i/3])

desc(x,n) = ((1<<(n-1)) + x) >> n      // 算术右移
cb(v)     = cbrtTab[clamp(v,0,3071)]

rgbToLabInPlace(p):
  for each pixel:
    r=srgbTab[p0], g=srgbTab[p1], b=srgbTab[p2]
    fx=cb(desc(coeffs[0]*r+coeffs[1]*g+coeffs[2]*b,12))
    fy=cb(desc(coeffs[3]*r+coeffs[4]*g+coeffs[5]*b,12))
    fz=cb(desc(coeffs[6]*r+coeffs[7]*g+coeffs[8]*b,12))
    p0=clip8(desc(fy*296 + (-1336934),15))
    p1=clip8(desc((fx-fy)*500 + 4194304,15))
    p2=clip8(desc((fy-fz)*200 + 4194304,15))

labToRgbInPlace(p):
  L=p0*100/255; a=p1-128; b=p2-128
  L<=8: yy=L/903.3; fy=yy*7.787+0.13793103448275862
  else: fy=(L+16)/116; yy=fy^3
  fx=a/500+fy; fz=fy-b/200
  x=(fx^3>0.008856 ? fx^3 : (fx-0.13793103448275862)/7.787)*0.950456
  z=(fz^3>0.008856 ? fz^3 : (fz-0.13793103448275862)/7.787)*1.088754
  R=gamma( 3.240479x -1.53715yy -0.498535z)*255
  G=gamma(-0.969256x +1.875991yy +0.041556z)*255
  B=gamma( 0.055648x -0.204043yy +1.057311z)*255
  gamma(v): clamp(v,0,1); <=0.0031308 ? 12.92v : 1.055*v^(1/2.4)-0.055
  结果 round 后 clamp 0..255

Fusion.fuse(orig, gan):
  require same size
  rgbToLabInPlace(orig); rgbToLabInPlace(gan)
  for c in 0..2:
    diff[i]=(gan_c[i]&255)-(orig_c[i]&255)
    Gaussian.blur(diff,w,h, c==0?25.0:20.0)
    orig_c[i]=clamp( (orig_c[i]&255)+diff[i], 0,255)   // 截断
  labToRgbInPlace(orig); return orig
```

## 8. 深度（LeicaEngine.depth）

```text
scale=min(1, 768/max(w,h)); aw=max(1,int(w*scale)); ah=max(1,int(h*scale))
analysis=Resample.resize(orig,aw,ah,LANCZOS)
(dw,dh)=depthSize(aw,ah)
input=LegendaryMath.resize(rgb(analysis), dw,dh, cubic=true, alignCorners=false)
mean=[0.485,0.456,0.406]; std=[0.229,0.224,0.225]
input[c]=(input[c]-mean[c])/std[c]
raw=run("depth", {"input": input}, channels=1)       // [1,3,dw,dh] -> [dw,dh]
raw=LegendaryMath.resize(raw, aw,ah, cubic=false, alignCorners=true)
return LegendaryMath.normalize(raw)
```

`normalize(raw)`：排序后取 2%/98% 分位（线性插值），
`out=clamp((v-lo)/(hi-lo),0,1)`；若 `hi-lo<1e-5` 抛错“原照片深度无法区分，请更换照片”。

## 9. 色彩迁移（GAN）

```text
gan = infer(GAN, decodeGanInput(uri)):
  NCHW float32，值 = ((byte/255)-0.5)/0.5 = 2v/255-1   // [-1,1]
  输入名 "input"；输出 shape 必须等于输入 shape
  回写 byte = (byte)(clamp(out*0.5+0.5,0,1)*255)       // 截断
colored = Fusion.fuse(original, Resample.resize(gan,w,h,BICUBIC))
```

`LeicaStyle.LEGENDARY.asset = leica/legendary-1.0-gan.fp16.onnx`，SHA 见 `LeicaEngine`。

## 10. 对焦点（LegendaryMath.focus）

```text
require depth 1ch, 所有值有限且 0<=v<=1
x=round(point.x*(W-1)); y=round(point.y*(H-1))
r=clamp(round(min(W,H)*0.006),1,8)
取 (x±r,y±r) 窗口（裁剪到边界），排序，med=50% 分位
reliable = (p90-p10 <= 0.08) && (abs(depth[y,x]-med) <= 0.04)
           && (max(depth)-min(depth) > 1e-5)
reliable ? med : null
```

`focus=null` 时 App 不执行虚化，只在已开启调色时输出调色结果。

## 11. 虚化主链路（LegendaryMath.render/renderCoc/multiscale）

```text
g=gain(aperture)
coc0=(depth - focus)*g                       // depth 分辨率
coc=LegendaryMath.resize(coc0, colored.w, colored.h, cubic=false, alignCorners=false)

renderCoc(colored,coc,aperture):
  if max(abs(coc)) < 1e-6: return colored
  hasHighlight = any(p0|p1|p2 > 136)
  if !hasHighlight:
      return planes(multiscale(rgb(colored), coc, infer))
  (base,high)=split(colored)
  if all(high==0):
      return planes(multiscale(base, coc, infer))
  rendered=multiscale(base,coc,infer)
  optical=scatter(high,coc,aperture)
  for each channel/pixel:
      rendered = srgb(linear(rendered) + optical)
  return planes(rendered)
```

### multiscale

```text
target=max(1, max(abs(coc))/8)
scale=1; previous=1; composite=null
loop:
  w=max(2, ceil(rgb.w/scale)); h=max(2, ceil(rgb.h/scale))
  actual = scale==1 ? max(rgb.w/w, rgb.h/h) : max(rgb.w/w, rgb.h/h)
  small = area(rgb,w,h)                 // 精确 box 平均；同尺寸直接返回
  df = LegendaryMath.resize(coc,w,h, bilinear)
  defocus = clamp((df/actual)/10, -1, 1)
  inferred = infer(small, defocus)      // ARNet {"image":small,"defocus":defocus}
  require 3ch, finite, w/h match; clamp [0,1]
  enlarged = LegendaryMath.resize(inferred, rgb.w,rgb.h, bilinear)
  if composite==null: composite=enlarged
  else:
    for each pixel:
      weight=smooth((abs(coc)-5*previous)/(3*previous))
      composite=composite*(1-weight)+enlarged*weight
  previous=actual
  if scale>=target: break
  scale=min(2*scale,target)
final:
  weight=smooth(abs(coc))
  output=quantize(rgb*(1-weight)+composite*weight)
```

`smooth(t)=t²(3-2t)`，`t=clamp(t,0,1)`；`quantize(x)=rint(clamp(x,0,1)*255)/255`。

### split（高光分离）

```text
for each pixel:
  r=linear(p0/255), g=linear(p1/255), b=linear(p2/255)
  ratio=min(1, 0.25/max(r,g,b,1e-8))
  base_c=quantize(srgb(value_c*ratio))
  high_c=max(0, value_c - linear(base_c))
```

### ARNet

```text
infer(image,defocus) -> Frame(3ch):
  input "image":   [1,3,h,w] float32 [0,1]
  input "defocus": [1,1,h,w] float32 [-1,1]
  output[0]: [1,3,h,w] float32
```

## 12. 高光散景（kernel / psfRows / scatter）

### kernel(radius, aperture)

```text
if radius==0: return Kernel(half=0, [1.0])
round = f/0.95->1.0, f/1.8->0.85, f/2.0->0.8, f/2.8->0.65, f/4.0->0.45, 其他->0.25
half=ceil(radius+0.5); w=2*half+1
for row,col in w×w:
  covered=0
  for yy in 0..7, xx in 0..7:
    dx=(col+(xx+0.5)/8-0.5)-half
    dy=(row+(yy+0.5)/8-0.5)-half
    theta=atan2(dy,dx)
    sector=((theta+20°)%40°+40°)%40°-20°
    polygon=cos(20°)/cos(sector)
    boundary=radius*(round+(1-round)*polygon)
    if hypot(dx,dy)<=boundary: covered++
  k[row,col]=covered/64
normalize k by sum
```

### psfRows(kernel)

```text
full=max(k)
for each row ky:
  a=first col with k==full; b=last col with k==full
  verify contiguous else a=-1,b=-2
  tx/tw = non-zero entries outside [a,b]
  lo=min(a or +inf, min(tx)); hi=max(b or -1, max(tx))
  emit row(dy=ky-half, a,b,run=full,tx,tw,lo,hi) if a>=0 or tx nonempty
```

### scatter(high, coc, aperture)

```text
bins[i]=round(coc[i]); levels=unique(sorted)
halfOf(r)= r==0?0:ceil(r+0.5); maxHalf=max(halfOf(abs(level)))
stride=2*maxHalf+W+1
present[level][sy] = row sy contains level
for level in levels:
  half=halfOf(abs(level)); rows=psfRows(kernel(abs(level),aperture))
  padded=W+2*half; colOf[p]=reflect(p-half,W)
  // 前缀和：对 high 中 bins==level 的像素，按 padded 列累计 mask/R/G/B
  for sy: prefix sums; pmin[sy]/pmax[sy]
  for y in 0..H-1:
    acc=[0]*(4W)  // mask,R,G,B
    for row in rows:
      sy=reflect(y+row.dy,H)
      if !present[level][sy] or pmin[sy]<0: continue
      x0=max(0,pmin[sy]-row.hi); x1=min(W-1,pmax[sy]-row.lo)
      if x0>x1: continue
      if row.a>=0:
        for x in x0..x1:
          p0=base+x+row.a; p1=base+x+row.b+1
          count=maskPrefix[p1]-maskPrefix[p0]
          acc[x]      += row.run*count
          acc[W+x]    += row.run*(rPrefix[p1]-rPrefix[p0])
          acc[2W+x]   += row.run*(gPrefix[p1]-gPrefix[p0])
          acc[3W+x]   += row.run*(bPrefix[p1]-bPrefix[p0])
      for (kx,weight) in row.taps:
        for x in x0..x1:
          src=sy*W+colOf[x+kx]
          if bins[src]==level:
            acc[x]    += weight
            acc[W+x]  += high[src]*weight
            acc[2W+x] += high[n+src]*weight
            acc[3W+x] += high[2n+src]*weight
    for x: alpha=acc[x]; if alpha!=0:
      keep=1-clamp(alpha,0,1)
      colorRGB[x]=accRGB[x]+colorRGB[x]*keep
      coverage[x]=clamp(alpha,0,1)+coverage[x]*keep
final: colorRGB[x] /= coverage[x] (coverage>1e-6 else 0)
```

## 13. LegendaryMath 其它工具

```text
rgb(Planes): Frame C,H,W float32 = (byte&255)/255
planes(Frame): Planes = byte(rint(clamp(v,0,1)*255))

cubic(x)  // Catmull-Rom a=-0.75
  |x|<=1: 1.25|x|^3 - 2.25|x|^2 + 1
  1<|x|<2: -0.75|x|^3 + 3.75|x|^2 - 6|x| + 3
  else 0

resize(Frame,w,h,cubic,alignCorners):
  同尺寸直接返回
  sy = alignCorners ? (h==1?0:y*(H-1)/(h-1)) : ((y+0.5)*H/h)-0.5
  sx 同理
  双线性：clamp 邻域 2×2，权重 (1-fy/fy),(1-fx/fx)
  双三次：clamp 邻域 4×4，权重 cubic(dy-fy)*cubic(dx-fx)

area(Frame,w,h): 精确面积平均（逐像素与源像素重叠面积加权，边界 clamp），sum/(sx*sy)

linear(x): x<=0.04045 ? x/12.92 : ((x+0.055)/1.055)^2.4
srgb(x):   x<=0.0031308 ? max(x,0)*12.92 : 1.055*max(x,0)^(1/2.4)-0.055
smooth(t): clamp(t,0,1)^2*(3-2*clamp(t,0,1))
quantize(x): rint(clamp(x,0,1)*255)/255
```

## 14. 模型 I/O

| 模型 | 文件 | 输入 | 输出 | 预处理 |
|---|---|---|---|---|
| depth | `legendary-1.0-depth.fp16.onnx` | `input [1,3,H,W] f32` | `output [H,W] f32` | ImageNet mean/std，短边≈518，14 对齐 |
| gan | `legendary-1.0-gan.fp16.onnx` | `input [1,3,H,W] f32` | `output [1,3,H,W] f32` | `2v/255-1`，短边 1024 |
| arnet | `legendary-1.0-arnet.fp16.onnx` | `image [1,3,H,W] f32`, `defocus [1,1,H,W] f32` | `output [1,3,H,W] f32` | image 为 [0,1]；defocus 为 [-1,1] |

模型 SHA-256：

```text
depth 70a6f853e9cb51d729055e48050b98c31d1bf29e5160d1b774253ce413d18a6d
arnet a3aa5fa6a0818f36dbfa4be4dd5471d874cea5981357b7aeb28919954e70d05c
gan   0cd65fb1215c04261735e6b2fa81c86646208bbf5d9a3339a56df6ee348ebd20
```

## 15. 顶层流程（LeicaEngine.process）

```text
process(uri, mode, aperture, focusPoint, outputSize, progress):
  require mode.blur ? focusPoint!=null : true
  gain(aperture)                             # 校验光圈
  # prepare
  (sw,sh)=EXIF 后的源尺寸
  (w,h)=processingSize(sw,sh,mode.blur,outputSize)
  work = mode.blur ? decodeWorking(uri,outputSize) : null
  depthMap = mode.blur ? depth(work.planes) : null
  focus = depthMap ? LegendaryMath.focus(depthMap, focusPoint) : null
  if mode.color:
      gan = infer(GAN, decodeGanInput(uri))
      original = work ? work.planes : decodeOriginal(uri)
      require original.size==(w,h)
      colored = Fusion.fuse(original, Resample.resize(gan,w,h,BICUBIC))
  else:
      colored = work.planes
      require colored.size==(w,h)
  # render
  rendered = mode.blur && focus!=null
  output = rendered ? LegendaryMath.render(colored, depthMap, focus, aperture) : colored
  # encode PNG RGB from Planes
```

## 16. 与 App 的已知差异

1. 解码器：Pillow/libjpeg vs Android BitmapFactory；不模拟 `inSampleSize`。算法一致，像素源不同。
2. 硬件：App 优先 NNAPI，本移植用 ONNX Runtime CPU。
3. PNG：App 用自研 `NativePng`（RGB8）；Web 端用 Pillow，像素一致、元数据可能不同。
4. 并行：App 用自定义 `parallelFor`；Python 用 numpy/OpenCV 的线程，运算顺序可能不同，
   float32 结果允许极小误差。
5. 大图：App 用 `BitmapRegionDecoder` 分块预览；后端以 Pillow + 自定义重采样实现解码，
   处理尺寸规则保持完全一致。

## 17. 移植验收

- `sizes`、`resample`、`lab`、`fusion`、`gaussian`、`focus`、`kernel`、`psfRows`、
  `multiscale`、`scatter` 与 JVM 黄金数据在 float32 容差内一致。
- 三个模型推理输出形状/有限性检查通过；同一输入下 Python 与 ORT 参考一致。
- 端到端：三种模式、不同光圈/焦点/输出尺寸、EXIF 旋转、高光场景均可出图。

## 18. 已完成验证（2026-10-17）

- JVM 黄金对照 23 项全部通过；Lab、三种 Resample、EXIF 转置逐字节一致。
  方法、容差与限制见 `docs/parity.md`。
- 高光散射的 Python 生产实现改为“按 CoC 层做 PSF 卷积 + 逐层衰减”，与逐行前缀和参考实现
  最大差异约 `1e-7`（float32 精度内）。
- 实测（i5-10210U，4 线程，3900×2600 输入；2026-10-17 复测）：
  - 仅调色：17.5 s，峰值 RSS 1.5 GB；
  - 仅虚化 2048：31.6 s，1.9 GB；
  - 调色＋虚化 2048：43.1 s（二次 42.7 s），1.9 GB。
- 此前空闲时同图约为 18.1 / 30.8 / 40.6 s；复测时系统 load average 约 5.5/8 线程，
  负载较高时 Web API 端到端约 49 s。
- 模型单次推理：depth 518×784 ≈3.9 s；GAN 1024×1536 ≈5.5 s；ARNet 2048×1365 ≈10.4 s。
