"""Display-only cleanup and deterministic native control placement."""
from __future__ import annotations
import re
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile


def normalize_text(value, *, vocabulary=True, latex=False):
    if not isinstance(value,str):return value
    # Preserve mathematical macros such as \ne, \neq, \nabla and \nu.
    value=re.sub(r'\\+r\\+n', '\n', value)
    value=re.sub(r'\\+newline(?![A-Za-z])', '\n', value)
    marker_tail=r'(?=$|[^A-Za-z]|[A-Za-z](?:\s*=|[_^]))'
    value=re.sub(r'\\+n(?!(?:e(?:q)?|abla|u|ot(?:in)?|eg|exists|i|leq|geq|mid|parallel)(?![A-Za-z]))'+marker_tail, '\n', value)
    value=re.sub(r'\\+r'+marker_tail, '\n', value)
    if vocabulary:
        for old,new in [('单调递增','随x的增大而增大'),('单调递减','随x的增大而减小'),('单调性','增减情况'),('极大值','最大值'),('极小值','最小值'),('极值','最值'),('闭区间','取值范围'),('开区间','取值范围'),('区间','范围')]:value=value.replace(old,new)
    if latex and '\n' in value:
        value=r'\begin{array}{l}'+r' \\ '.join(value.splitlines())+r'\end{array}'
    return value


def normalize_spec_text(spec):
    for key in ['title','problem_text']:
        if key in spec:spec[key]=normalize_text(spec[key],vocabulary=False)
    if 'formula_texts' in spec:spec['formula_texts']={key:normalize_text(value,latex=True) for key,value in spec['formula_texts'].items()}
    return spec


def _set(element,tag,values):
    child=element.find(tag)
    if child is None:child=ET.SubElement(element,tag)
    child.attrib.update({k:str(v) for k,v in values.items()});return child


def control_bottom(root):
    bottom=30
    for element in root.findall('./construction/element'):
        if element.get('type')=='boolean':
            offset=element.find('labelOffset')
            if offset is not None:bottom=max(bottom,float(offset.get('y','0'))+28)
        elif element.get('type')=='numeric':
            slider=element.find('slider')
            if slider is not None and slider.get('absoluteScreenLocation')=='true':bottom=max(bottom,float(slider.get('y','0'))+40)
    return bottom


def layout_native_controls(path:Path,spec):
    with zipfile.ZipFile(path) as archive:
        root=ET.fromstring(archive.read('geogebra.xml'));elements={e.get('label'):e for e in root.findall('./construction/element')}
        for label,element in elements.items():
            caption=element.find('caption')
            if caption is not None:caption.set('val',re.sub(r'(?:动态|动)?范围(?=求)', '', ' '.join(normalize_text(caption.get('val','')).split())))
            if element.get('type')!='text' or label in {'ExamProblemText','ExamProblemOCRFull'}:continue
            expression=root.find('./construction/expression[@label="'+label+'"]')
            if expression is not None:
                value=expression.get('exp','')
                # Only static text literals; preserve symbolic/dynamic text expressions.
                if re.fullmatch(r'"(?:\\.|[^"\\])*"',value,re.S):
                    latex=element.find('isLaTeX')
                    text=normalize_text(value[1:-1],latex=latex is not None and latex.get('val')=='true')
                    expression.set('exp','"'+text+'"')
        mains=[label for label in spec.get('mutual_exclusive_controls',[]) if label in elements and label!='ShowTextOn']
        children={label:[] for label in mains};unowned=[]
        jumps=spec.get('slider_jumps',{});jump_labels={item['label'] for item in jumps.get('items',[])};jump_slider=jumps.get('slider');parent=jumps.get('parent_control')
        binding_owners={b['label']:b.get('condition','') for b in spec.get('script_bindings',[])}
        for label,element in elements.items():
            if label in mains or label=='ShowTextOn':continue
            slider=element.find('slider');show=element.find('show')
            is_slider=element.get('type')=='numeric' and slider is not None and (label==jump_slider or slider.get('absoluteScreenLocation')=='true' and show is not None and show.get('object')=='true')
            is_boolean=element.get('type')=='boolean' and (label in jump_labels or show is not None and show.get('object')=='true')
            if not (is_slider or is_boolean):continue
            condition=element.find('condition');condition_text=binding_owners.get(label,'') or (condition.get('showObject','') if condition is not None else '')
            owner=parent if label==jump_slider or label in jump_labels else next((m for m in mains if re.search(r'\b'+re.escape(m)+r'\b',condition_text)),None)
            (children[owner] if owner in children else unowned).append(label)
        # Keep slider before its jump controls; preserve all conditions and scripts.
        for values in children.values():values.sort(key=lambda name:0 if elements[name].get('type')=='numeric' else 1)
        rows=[];y=88
        def position(label,child=False):
            nonlocal y
            element=elements[label];x=35 if child else 25
            if element.get('type')=='numeric':
                _set(element,'slider',{'x':x,'y':y,'width':180,'absoluteScreenLocation':'true','horizontal':'true'});y+=48
            else:_set(element,'labelOffset',{'x':x,'y':y});y+=36
            rows.append({'label':label,'x':x,'y':y-(48 if element.get('type')=='numeric' else 36),'type':element.get('type')})
        for label in mains:
            position(label)
            for child in children[label]:position(child,True)
        for label in unowned:position(label,True)
        temporary=path.with_suffix('.controls.ggb')
        xml=ET.tostring(root,encoding='utf-8',xml_declaration=True)
        with zipfile.ZipFile(temporary,'w',compression=zipfile.ZIP_DEFLATED) as out:
            for item in archive.infolist():out.writestr(item,xml if item.filename=='geogebra.xml' else archive.read(item.filename))
    temporary.replace(path)
    return {'status':'pass','rows':rows,'bottom':control_bottom(root)}
