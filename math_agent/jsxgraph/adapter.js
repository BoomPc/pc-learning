/* Thin adapter: geometry, object dependencies, clipping and drawing are JSXGraph's. */
(() => {
  'use strict';
  const spec = JSON.parse(document.getElementById('lesson-data').textContent);
  const states = [], faults = [];
  const el = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
  const math = {sin: Math.sin, cos: Math.cos, tan: Math.tan, sqrt: Math.sqrt, abs: Math.abs, min: Math.min, max: Math.max};
  function arithmetic(tree, t, x) {
    if (typeof tree === 'number') return tree;
    const [op, ...nodes] = tree;
    if (op === 'var') return nodes[0] === 'x' ? x : t;
    const a = nodes.map(n => arithmetic(n, t, x));
    if (math[op]) return math[op](...a);
    switch (op) {
      case '+': return a[0]+a[1]; case '-': return a[0]-a[1]; case '*': return a[0]*a[1];
      case '/': return a[0]/a[1]; case 'pow': return Math.pow(a[0],a[1]);
      case 'mod': return ((a[0]%a[1])+a[1])%a[1]; case 'neg': return -a[0]; case 'pos': return a[0];
      default: throw Error('未知算术节点');
    }
  }
  function snapshot(index) {
    const s = states[index], objects = {};
    for (const d of s.definition.board.objects) {
      const o = s.objects[d.id], data = {kind: d.kind, nativeType: o.elType};
      if (o.elementClass === JXG.OBJECT_CLASS_POINT) { data.x = o.X(); data.y = o.Y(); data.screen = o.coords.scrCoords.slice(1); }
      if (o.elementClass === JXG.OBJECT_CLASS_LINE) data.coefficients = o.stdform.slice(0,3);
      if (d.kind === 'segment') {
        data.length = o.L();
        data.endpoints = [[o.point1.X(),o.point1.Y()],[o.point2.X(),o.point2.Y()]];
      }
      if (d.kind === 'circle') data.radius = o.Radius();
      if (d.kind === 'polygon') data.vertices = o.vertices.map(p => [p.X(),p.Y()]);
      objects[d.id] = data;
    }
    return JSON.parse(JSON.stringify({t: s.t, inDomain: s.inDomain, viewport:s.board.getBoundingBox(), objects}));
  }
  function fitView(s) {
    // Expand only the viewport to the container aspect ratio; never alter geometry.
    const width=s.box.clientWidth,height=s.box.clientHeight;
    if (!width || !height || s.fitting) return;
    let [left,top,right,bottom]=s.definition.board.bounding_box;
    if(s.definition.board.viewport==='fit_points') {
      const points=s.definition.board.objects.filter(d=>d.visible && s.objects[d.id]?.elementClass===JXG.OBJECT_CLASS_POINT)
        .map(d=>[s.objects[d.id].X(),s.objects[d.id].Y()]).filter(p=>p.every(Number.isFinite));
      if(points.length) {
        const xs=points.map(p=>p[0]),ys=points.map(p=>p[1]);
        const loX=Math.min(...xs),hiX=Math.max(...xs),loY=Math.min(...ys),hiY=Math.max(...ys);
        const span=Math.max(hiX-loX,hiY-loY,1);
        // Include room for point labels; never replace coordinates or skip invalid-object checks.
        const pad=Math.max(span*.12, .25);
        [left,top,right,bottom]=[loX-pad,hiY+pad,hiX+pad,loY-pad];
      }
    }
    // Mathematical bounds describe the requested region, not a pixel-tight crop.
    // Leave a small screen-space gutter for points on its edges; never move them.
    const gutter=Math.min(12,width/8,height/8);
    const unit=Math.max((right-left)/(width-2*gutter),(top-bottom)/(height-2*gutter));
    const cx=(left+right)/2,cy=(top+bottom)/2;
    s.fitting=true;
    try {
      if(s.board.canvasWidth!==width || s.board.canvasHeight!==height) s.board.resizeContainer(width,height);
      s.board.setBoundingBox([cx-unit*width/2,cy+unit*height/2,cx+unit*width/2,cy-unit*height/2],false);
      s.board.keepaspectratio=true;
    } finally {s.fitting=false;}
  }
  function select(index) {
    states.forEach((s, i) => {s.panel.classList.toggle('active', i === index); s.tab.classList.toggle('active', i === index);});
    fitView(states[index]);
  }
  function construct(definition, index) {
    const panel = el('section', undefined, 'answer-panel');
    const tab = el('button', definition.tab_title, 'tab-btn'); tab.type = 'button';
    document.getElementById('tabs').append(tab); document.getElementById('panels').append(panel);
    const layout = el('div', undefined, 'lesson-grid'), figure = el('div', undefined, 'figure-card'), explanation = el('div', undefined, 'explanation');
    panel.append(layout); layout.append(figure, explanation);
    figure.append(el('p', '拖动画布平移 · 滚轮缩放', 'figure-hint'));
    const box = el('div', undefined, 'jxgbox'); box.id = 'board-'+index; figure.append(box);
    const s = {definition, panel, tab, box, objects: Object.create(null), t: definition.controls?.slider.default ?? 0, inDomain: true};
    states.push(s);
    const board = s.board = JXG.JSXGraph.initBoard(box.id, {
      boundingbox: definition.board.bounding_box, keepaspectratio: true, axis: definition.board.axis,
      showCopyright: true, showNavigation: false, renderer: 'svg', animationDelay: 30,
      pan: {enabled: true, needShift: false}, zoom: {enabled: true, wheel: true, needShift: false},
      defaultAxes: {x: {strokeColor:'#71849e', ticks:{strokeColor:'#71849e',label:{strokeColor:'#b6c8dc'}}}, y: {strokeColor:'#71849e',ticks:{strokeColor:'#71849e',label:{strokeColor:'#b6c8dc'}}}}
    });
    const fn = tree => x => arithmetic(tree, s.t, x);
    for (const d of definition.board.objects) {
      const parents = (d.parents || []).map(id => s.objects[id]);
      const attrs = {name: d.label || d.id, visible: d.visible, strokeColor: d.color, fillColor: d.color,
        highlight: false, fixed: true, dash: d.dashed ? 2 : 0, strokeWidth: 2, size: 3,
        label: {display:'internal', parse:false, useMathJax:false, autoPosition:true, strokeColor:'#e8f1ff', fontSize:15, offset:[10,10]},
        withLabel: false, fillOpacity:0};
      let o;
      if (['point','midpoint','intersection','perpendicularpoint','reflection','rotation','translation','glider'].includes(d.kind)) {attrs.withLabel = true; attrs.fillOpacity = 1;}
      switch (d.kind) {
        case 'point': o = board.create('point', d.coords.map(fn), attrs); break;
        case 'functiongraph': o = board.create('functiongraph', [fn(d.expression), ...d.domain], attrs); break;
        case 'rotation': {
          const angle=d.direction ? ()=>{
            const degrees=arithmetic(d.degrees,s.t);
            if(!Number.isFinite(degrees) || degrees<0) throw Error('旋转角度大小须非负且有限：'+d.id);
            return (d.direction==='clockwise'?-1:1)*degrees*Math.PI/180;
          } : fn(d.angle);
          const transform = board.create('transform', [angle, parents[1]], {type:'rotate'});
          o = board.create('point', [parents[0], transform], attrs); break;
        }
        case 'translation': {
          const transform = board.create('transform', d.vector.map(fn), {type:'translate'});
          o = board.create('point', [parents[0], transform], attrs); break;
        }
        case 'intersection': o = board.create('intersection', [...parents, d.branch], attrs); break;
        case 'circle': o = board.create('circle', d.radius === undefined ? parents : [...parents, fn(d.radius)], attrs); break;
        case 'polygon': o = board.create('polygon', parents, {...attrs, fillOpacity:.14, borders:{strokeColor:d.color,strokeWidth:2,highlight:false}}); break;
        case 'angle': o = board.create('angle', parents, {...attrs, selection:'minor', radius:.45, fillOpacity:.2}); break;
        case 'glider': o = board.create('glider', [...d.coords, ...parents], {...attrs, fixed:false}); break;
        default: o = board.create(d.kind, parents, attrs);
      }
      s.objects[d.id] = o;
    }
    const restore = el('button', '恢复视图', 'secondary'); restore.type='button'; restore.onclick=()=>fitView(s); figure.append(restore);
    if (definition.controls) {
      const c = definition.controls, domain = c.slider, controls = el('div', undefined, 'controls');
      const label = el('label', domain.label+' = '), output = el('output'); label.append(output);
      const slider = el('input'); slider.type='range'; slider.min=domain.min; slider.max=domain.max; slider.step='any'; slider.value=s.t;
      slider.setAttribute('aria-label',domain.label); const note = el('p', undefined, 'domain-note');
      s.slider=slider;
      s.set = value => {
        if (!Number.isFinite(value) || value < domain.min || value > domain.max) throw Error('参数超出范围');
        slider.value=value; s.t=+slider.value;
        s.inDomain=!(s.t === domain.min && !domain.min_inclusive || s.t === domain.max && !domain.max_inclusive);
        slider.dataset.inDomain=String(s.inDomain); output.textContent=Number(s.t.toPrecision(10)).toString();
        note.textContent=(domain.min_inclusive?'[':'(')+domain.min+', '+domain.max+(domain.max_inclusive?']':')')+(s.inDomain?'':' · 此端点不包含在题设中，仅观察边界');
        board.update();
        if(definition.board.viewport==='fit_points') fitView(s);
      };
      slider.addEventListener('input',()=>s.set(+slider.value));
      slider.addEventListener('keydown',e=>{if(['ArrowLeft','ArrowRight'].includes(e.key)){e.preventDefault();s.set(Math.min(domain.max,Math.max(domain.min,s.t+(e.key==='ArrowRight'?1:-1)*domain.step)));}});
      controls.append(label,slider,note);
      const jumps = el('div', undefined, 'jumps');
      const buttons=[...c.jump_buttons];
      for(const value of c.solution_targets) if(!buttons.some(b=>b.value===value)) buttons.push({text:'答案 t = '+value,value,is_target:true});
      for (const jump of buttons) {const b=el('button',(jump.is_target?'答案 · ':'观察 · ')+jump.text,'jump-btn');b.type='button';b.onclick=()=>s.set(jump.value);jumps.append(b);}
      controls.append(jumps); figure.append(controls); s.set(s.t);
    }
    explanation.append(el('p', '解题过程', 'eyebrow'));
    definition.steps.forEach((step,i)=>{const item=el('div',undefined,'step');item.append(el('h3',(i+1)+'. '+step.head),el('p',step.content));explanation.append(item);});
    const answer=el('div',undefined,'conclusion');answer.append(el('strong','结论'),el('p',definition.conclusion));explanation.append(answer);
    tab.onclick=()=>select(index);
    const resize=new ResizeObserver(()=>{if(panel.classList.contains('active')) {fitView(s);}});resize.observe(box);
  }
  try {
    document.getElementById('title').textContent=spec.title; document.getElementById('problem').textContent=spec.problem_text;
    spec.tabs.forEach(construct); select(0);
    window.mathAgent = {engine:'JSXGraph', version:JXG.version, states, snapshot, select, faults,
      setParameter:(index,value)=>states[index].set(value)};
    document.documentElement.dataset.ready='true';
  } catch(error) {
    faults.push(String(error)); document.getElementById('error').textContent='图形构造失败：'+String(error); throw error;
  }
})();
