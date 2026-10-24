"""Linux JSON-only adapter for the supplied webpage assembler and template."""
from __future__ import annotations
import ast
import base64
import copy
import html
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import textwrap
import time
from expression_runtime import normalized
from presentation import normalize_text
import base_pipeline as base
from base_pipeline import (PipelineError, SpecValidationError, ProblemNeedsClarification,
    DEFAULT_MODEL, MAX_EVENT_BYTES, _kill_group, _public_error, _write)

HERE = Path(__file__).resolve().parent
VENDOR = HERE/'vendor'
NAME = re.compile(r"[A-Za-z][A-Za-z0-9_']{0,39}\Z")
ALLOWED = {'title','problem_text','tabs','stage'}
FORBIDDEN = {'img_path','img_base64','problem_image_base64','custom_svg','svg','dynamic_script','page_scripts','onclick','onchange','oninput','onload'}
TEXT_KEYS = {'title','problem_text','tab_title','tab_name','head','content','conclusion','text','slider_label','label','xLabel','yLabel'}


def expression(value):
    if isinstance(value, (float,int)) and not isinstance(value,bool):
        if not math.isfinite(value) or abs(value)>1e6:raise SpecValidationError('数值超出范围')
        return value
    if not isinstance(value,str) or len(value)>200:raise SpecValidationError('数学表达式无效')
    value=normalized(value)
    try:tree=ast.parse(value,mode='eval')
    except SyntaxError:raise SpecValidationError('数学表达式语法无效') from None
    nodes=list(ast.walk(tree))
    if len(nodes)>80:raise SpecValidationError('数学表达式过于复杂')
    allowed=(ast.Expression,ast.BinOp,ast.UnaryOp,ast.Call,ast.Name,ast.Load,ast.Constant,
             ast.Add,ast.Sub,ast.Mult,ast.Div,ast.Pow,ast.Mod,ast.UAdd,ast.USub)
    names=set('abcdefghijklmnopqrstuvwxyz')|{'pi','abs','min','max','sqrt','sin','cos','tan'}
    for node in nodes:
        if not isinstance(node,allowed):raise SpecValidationError('表达式只允许数学运算')
        if isinstance(node,ast.Name) and node.id not in names:raise SpecValidationError('表达式变量或函数不支持')
        if isinstance(node,ast.Constant):
            if isinstance(node.value,bool) or not isinstance(node.value,(float,int)) or not math.isfinite(node.value) or abs(node.value)>1e6:raise SpecValidationError('表达式常量无效')
        if isinstance(node,ast.Call) and (not isinstance(node.func,ast.Name) or node.func.id not in {'abs','min','max','sqrt','sin','cos','tan'} or node.keywords or not 1<=len(node.args)<=4):raise SpecValidationError('函数调用不支持')
        if isinstance(node,ast.BinOp) and isinstance(node.op,ast.Pow):
            if not isinstance(node.right,ast.Constant) or abs(node.right.value)>12:raise SpecValidationError('指数超出安全范围')
    return value


def validate_spec(raw):
    if isinstance(raw,dict) and set(raw)=={'error'}:
        raise ProblemNeedsClarification(base._text(raw['error'],'读题提示',600))
    if not isinstance(raw,dict) or set(raw)-ALLOWED or not {'title','tabs'}<=set(raw):raise SpecValidationError('网页数据字段不完整或不支持')
    if len(json.dumps(raw,ensure_ascii=False).encode())>512*1024:raise SpecValidationError('网页数据过大')
    result=copy.deepcopy(raw)
    title=base._text(result['title'],'标题',100)
    if any(c in title for c in '/\\\r\n\t') or title in {'.','..'}:raise SpecValidationError('标题不能是文件路径')
    if not isinstance(result['tabs'],list) or not 1<=len(result['tabs'])<=12:raise SpecValidationError('小问数量必须为1至12')
    def walk(value,key='',depth=0):
        if depth>20:raise SpecValidationError('数据嵌套过深')
        if isinstance(value,dict):
            if set(value)&FORBIDDEN:raise SpecValidationError('仅允许声明式数据，不允许脚本、SVG或文件路径')
            for k,v in list(value.items()):value[k]=walk(v,k,depth+1)
        elif isinstance(value,list):
            if len(value)>200:raise SpecValidationError('图元数量过多')
            value=[walk(v,key,depth+1) for v in value]
        elif isinstance(value,str):
            if len(value)>20000 or '\x00' in value:raise SpecValidationError('文本过长或无效')
            if key in {'expr','x','y','ratio','r'}:return expression(value)
            if key in TEXT_KEYS:
                # Persisted rounds already contain escaped display text.
                for _ in range(3):
                    decoded=html.unescape(value)
                    if decoded==value:break
                    value=decoded
                return html.escape(normalize_text(value,vocabulary=key not in {"title","problem_text"}),quote=True)
            if key=='viewBox' and not re.fullmatch(r'[-0-9. ]{7,60}',value):raise SpecValidationError('视口格式无效')
            if key in {'name','id','slider_id','p1','p2','center'} and not NAME.fullmatch(value):raise SpecValidationError('图元名称无效')
            if key in {'color','fill','stroke'} and not re.fullmatch(r'(?:#[A-Fa-f0-9]{3,8}|none|transparent)',value):raise SpecValidationError('颜色格式无效')
            if any(c in value for c in '<>"`') or '://' in value:raise SpecValidationError('数据包含不支持的标记')
        elif isinstance(value,(float,int)) and not isinstance(value,bool):expression(value)
        elif value is not None and not isinstance(value,bool):raise SpecValidationError('数据类型无效')
        return value
    result=walk(result)
    for tab in result['tabs']:
        if not isinstance(tab,dict) or not {'tab_title','steps','conclusion'}<=set(tab):raise SpecValidationError('每个小问需标题、步骤与结论')
        if tab.get('type','static') not in {'static','dynamic'}:raise SpecValidationError('小问类型无效')
        if tab.get('type','static')=='static' and tab.get('controls'):raise SpecValidationError('静态小问不能添加滑条')
    return result


def context():
    return '\n原附件 GEMINI.md 中的数学、声明式图元及界面规范（忽略其中本地路径和模型执行命令步骤）：\n'+(VENDOR/'GEMINI.md').read_text()+'\n原附件数据Schema：\n'+(HERE/'native-spec.schema.json').read_text()


def module(path,name):
    spec=importlib.util.spec_from_file_location(name,path);loaded=importlib.util.module_from_spec(spec);spec.loader.exec_module(loaded);return loaded


def question_image(spec, directory):
    from PIL import Image,ImageDraw,ImageFont
    roles_path=directory.parent/'image-roles.json'
    roles=json.loads(roles_path.read_text()) if roles_path.is_file() else {}
    paths=[path for path in sorted(directory.parent.glob('input-*')) if roles.get(path.name)!='answer']
    tiles=[]
    for p in paths:
        with Image.open(p) as im:
            im=im.convert('RGB');width=min(1000,im.width);tiles.append(im.resize((width,max(1,round(im.height*width/im.width)))))
    if not tiles:
        font=ImageFont.truetype(os.environ['GGB_FONT_FILE'],24)
        text=html.unescape(spec.get('problem_text',spec['title']))
        lines=[line for paragraph in text.splitlines() for line in (textwrap.wrap(paragraph,38) or [''])]
        im=Image.new('RGB',(1000,max(100,50+len(lines)*36)),'white');draw=ImageDraw.Draw(im)
        draw.multiline_text((25,25),'\n'.join(lines),font=font,fill='black',spacing=8);tiles=[im]
    height=sum(t.height+12 for t in tiles)
    if height>30000:
        factor=30000/height;tiles=[t.resize((max(1,int(t.width*factor)),max(1,int(t.height*factor)))) for t in tiles]
    canvas=Image.new('RGB',(max(t.width for t in tiles),sum(t.height+12 for t in tiles)),'white');y=0
    for tile in tiles:canvas.paste(tile,(0,y));y+=tile.height+12
    path=directory/'source-collage.png';canvas.save(path);return path


def _export_impl(spec,directory,timeout,on_stage):
    started=time.monotonic();on_stage and on_stage('正在装配离线交互网页')
    assembler=module(VENDOR/'scripts/assembler.py','supplied_web_assembler')
    data=copy.deepcopy(spec);data['img_base64']=base64.b64encode(question_image(spec,directory).read_bytes()).decode()
    output,checks=assembler.assemble_problem_page(data,str(directory/'assembled'))
    failed=[k for k,v in checks.items() if not v]
    if failed:raise PipelineError('网页装配检查失败：'+'；'.join(failed))
    result=directory/'result.html';shutil.copyfile(output,result)
    on_stage and on_stage('正在验证网页交互与预览')
    from playwright.sync_api import sync_playwright
    errors=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,executable_path=os.environ['GGB_CHROMIUM_EXECUTABLE'])
        page=browser.new_page(viewport={'width':1200,'height':1000})
        page.on('pageerror',lambda error:errors.append(str(error)[:1000]))
        page.on('console',lambda message:errors.append(message.text[:1000]) if message.type=='error' else None)
        page.route('**/*',lambda route:route.continue_() if route.request.url==result.as_uri() else route.abort())
        page.goto(result.as_uri(),wait_until='load',timeout=min(30000,max(1000,int(timeout*1000))))
        buttons=page.locator('.tab-btn');assert buttons.count()==len(spec['tabs'])
        for index in range(buttons.count()):buttons.nth(index).click();page.locator('.answer-panel.active').wait_for(state='visible')
        for index in range(buttons.count()):
            buttons.nth(index).click()
            for slider in page.locator('.answer-panel.active input[type=range]').all():
                slider.evaluate("s => {const lo=+s.min,hi=+s.max;for(let i=0;i<=10;i++){s.value=lo+(hi-lo)*i/10;s.dispatchEvent(new Event('input',{bubbles:true}));}}")
            for button in page.locator('.answer-panel.active .jump-btn').all(): button.click()
            bad=page.locator('.answer-panel.active svg').evaluate_all("svgs => svgs.some(s=>[...s.querySelectorAll('*')].some(e=>[...e.attributes].some(a=>['cx','cy','x','y','x1','x2','y1','y2','r','points','d'].includes(a.name)&&/NaN|Infinity/.test(a.value))))")
            if bad: errors.append('SVG 存在非有限坐标')
        buttons.first.click();page.screenshot(path=str(directory/'preview.png'),full_page=False)
        browser.close()
    if errors:raise PipelineError('网页运行校验失败：'+'；'.join(errors))
    if time.monotonic()-started>timeout:raise TimeoutError('网页导出超过时间上限')
    _write(directory/'export-check.json',{'status':'pass','engine':'supplied assembler + template','checks':checks,'tabs':len(spec['tabs']),'browser_errors':errors,'seconds':round(time.monotonic()-started,3),'output':'result.html'})
    return result

def export(spec,directory,timeout,on_stage):
    try:return _export_impl(spec,directory,timeout,on_stage)
    except (PipelineError,TimeoutError):raise
    except Exception as exc:raise PipelineError("网页装配或交互检查失败："+str(exc)[:2500]) from exc

base.validate_spec=validate_spec
base._skill_context=context
base._export=export
run_job=base.run_job
