export const fontPolicy = { basis: 'design', families: ['Microsoft YaHei'] };

const C = { ink: '#21372F', green: '#227451', muted: '#60756B', line: '#D5E2DA', pale: '#EDF4EF', dark: '#143C2B', white: '#FFFFFF', amber: '#94672B' };
const FONT = 'Microsoft YaHei';
const W = 1920, H = 1080;
let n = 0;

function text(s, name, value, x, y, w, h, size=36, color=C.ink, bold=false, align='left') {
  const a = s.shapes.add({name, geometry:'textbox', position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
  a.text = value;
  a.text.style = {typeface:FONT,fontSize:size,color,bold,alignment:align,verticalAlignment:'top',insets:0,autoFit:'none',wrap:'square'};
  return a;
}
function line(s,x,y,w,color=C.line,width=2) {
  return s.shapes.add({geometry:'line',position:{left:x,top:y,width:w,height:0},fill:'none',line:{fill:color,width,style:'solid'}});
}
function base(p,title,subtitle='') {
  const s=p.slides.add({width:W,height:H});
  s.background.fill=C.white;
  n++;
  text(s,'slide-title',title,100,76,1700,105,57,C.ink,true);
  if(subtitle) text(s,'slide-subtitle',subtitle,104,187,1680,70,29,C.muted);
  line(s,100,972,1720);
  text(s,'footer','issue-tracker 项目成果汇报',104,998,1350,35,22,C.muted);
  text(s,'page-number',String(n).padStart(2,'0'),1710,994,100,40,24,C.muted,false,'right');
  return s;
}
function notes(s,seconds,body,source='docs/issue-tracker项目成果汇报-15分钟版.md') {
  s.speakerNotes.text=`建议讲述时长：${seconds} 秒。\n\n${body}\n\n资料来源：${source}。项目功能以当前代码及 README 为依据。`;
}
function rows(s,items,x=110,y=290,w=1690,gap=195) {
  items.forEach(([heading,body],i)=>{
    const yy=y+i*gap;
    text(s,`row-${i}-number`,String(i+1).padStart(2,'0'),x,yy,105,66,48,C.green,true);
    text(s,`row-${i}-heading`,heading,x+140,yy,w-140,68,40,C.ink,true);
    text(s,`row-${i}-body`,body,x+140,yy+80,w-160,93,32,C.muted);
    if(i<items.length-1) line(s,x+140,yy+gap-25,w-160);
  });
}
function table(s,values,{x=104,y=300,w=1710,h=535,widths,fs=31}={}) {
  const t=s.tables.add({rows:values.length,columns:values[0].length,left:x,top:y,width:w,height:h,values,columnWidths:widths});
  t.styleOptions={headerRow:true,bandedRows:false};
  t.borders.assign({fill:C.line,width:1,style:'solid'});
  t.cells.block({row:0,column:0,rowCount:values.length,columnCount:values[0].length}).assign({margins:{top:22,bottom:18,left:24,right:24}});
  values.forEach((row,r)=>{
    t.rows[r].height = r===0 ? 96 : (h-96)/(values.length-1);
    row.forEach((_,c)=>{
      const cell=t.getCell(r,c);
      cell.fill=r===0?C.green:C.white;
      cell.text.style={typeface:FONT,fontSize:r===0?fs+1:fs,bold:r===0,color:r===0?C.white:C.ink,wrap:'square',autoFit:'none',verticalAlignment:'middle'};
    });
  });
  return t;
}

export async function buildReport(p,imageBytes) {
  if(p.slides.items.length) throw new Error('Build expects a new empty presentation');
  n=0;

  // 1. Minimal cover. All title and supporting text stays editable.
  let s=p.slides.add({width:W,height:H}); n++;
  s.background.fill=C.dark;
  text(s,'cover-project','issue-tracker',110,172,1630,135,108,C.white,true);
  text(s,'cover-title','项目成果汇报',116,354,1660,120,78,C.white,true);
  text(s,'cover-subtitle','社区问题跟踪与 AI 辅助测试分析',120,547,1640,95,44,'#D5E8DD');
  text(s,'cover-date','2026 年 10 月',120,881,1000,55,28,'#D5E8DD');
  notes(s,30,'各位好，今天汇报 issue-tracker 项目的阶段成果。这个项目的目标是让社区中有价值的问题更快进入我们的分析和测试视野，并把结果持续积累下来。目前已经建立了问题同步、统一管理、AI 辅助分析、优先筛选和人工确认的工作流程。下面介绍建设背景、完成的能力，以及下一阶段如何验证实际价值。');

  // 2. Three clear pain points, with no invented performance numbers.
  s=base(p,'建设背景与工作痛点','模型、硬件和软件版本的组合，使社区问题分析需要持续投入');
  rows(s,[
    ['持续跟进成本高','新增 Issue、历史评论和状态变化，需要反复收集与核对。'],
    ['测试投入难选择','真实缺陷、文档和咨询混杂，价值与复现条件需要逐条判断。'],
    ['分析经验难复用','结论分散在表格和文档中，交接与专题分析容易重复阅读。'],
  ]);
  notes(s,65,'以 vLLM Ascend 为例，一次推理失败可能涉及模型、量化方式、并行策略、硬件型号和软件版本。关键日志和结论还可能出现在后续评论里。依靠人工浏览，首先要持续跟进变化，其次要判断哪些问题值得投入硬件和分析时间，最后还需要让已有结论能够复用。项目针对的就是这些具体工作成本。');

  // 3. Preserve the original source diagram, including its qualifications.
  s=p.slides.add({width:W,height:H}); n++;
  s.background.fill=C.white;
  s.images.add({blob:imageBytes,contentType:'image/png',alt:'社区 Issue 测试转化影响因素鱼骨图',fit:'contain',position:{left:0,top:0,width:W,height:H}});
  notes(s,60,'这张鱼骨图把建设背景分成六个方面。信息获取涉及持续跟进和材料分散。分析方法涉及统一标准与资料整理。环境配置涉及模型、硬件、版本和关键参数。人员协作、工作流程和知识沉淀，则影响交接和结果复用。图中列出的是潜在影响因素，需要结合实际工作核查。它帮助我们说明项目为什么需要同时提供数据、分析和记录能力。','docs/figures/issue-tracker-fishbone.png，docs/issue-tracker项目成果汇报-15分钟版.md');

  // 4. Editable process diagram. Boxes denote actual workflow states.
  s=base(p,'已落地的工作流程','社区信息持续更新，AI 建议进入人工审核与本地分析记录');
  const stages=[['同步汇集','全量同步\n增量更新与校准'],['范围筛选','日期、状态、标签\n版本与分析字段'],['AI 辅助分析','正文与评论归纳\n结构化补测建议'],['人工审核','核查证据\n选择采纳并保存'],['分析沉淀','版本支持与状态记录\n筛选导出']];
  let previousNode;
  stages.forEach(([title,body],i)=>{
    const x=104+i*346;
    const node=s.shapes.add({name:`workflow-stage-${i}`,geometry:'rect',position:{left:x,top:330,width:300,height:220},fill:C.pale,line:{fill:C.line,width:2}});
    text(s,`workflow-title-${i}`,title,x+22,361,256,62,37,C.green,true);
    text(s,`workflow-body-${i}`,body,x+22,443,256,92,27,C.ink);
    if(previousNode) s.shapes.connect(previousNode,node,{kind:'straight',fromSide:'right',toSide:'left',line:{fill:C.green,width:3},tail:{type:'triangle',width:'sm',length:'sm'}});
    previousNode=node;
  });
  text(s,'workflow-followup-title','后续测试工作',112,687,1600,65,38,C.ink,true);
  text(s,'workflow-followup','人工复现、最小用例提炼与 CI 回归仍需进一步衔接。',112,772,1660,105,36,C.muted);
  notes(s,65,'已经落地的流程，从社区数据汇集开始，通过筛选确定范围，由 AI 形成结构化建议，再由人工核查和采纳，最后保存在统一台账中。同步更新社区侧字段，人工分析单独保留。当前已经具备记录版本支持和闭环状态的能力，但人工复现、测试用例入库以及 CI 执行仍是需要继续推进的工作。');

  // 5. Native evidence table of functionality and its operational purpose.
  s=base(p,'已完成的核心能力','单条分析与阶段性的集中梳理，使用同一套数据和分析入口');
  table(s,[['工作环节','已实现能力','对实际工作的作用'],
    ['数据同步','全量同步、默认 15 分钟增量同步、全量校准','持续跟进社区问题变化'],
    ['批量分析','勾选或筛选创建任务，可配置并发','支持集中梳理一批问题'],
    ['任务运行','进度、重试、取消、中断任务恢复','持续跟踪任务和失败项'],
    ['结果管理','建议独立保存、人工采纳、筛选导出','积累分析材料，支持交接和评审'],
  ],{widths:[275,800,635],fs:30,h:580});
  notes(s,65,'这里集中说明目前能够实际使用的能力。数据侧有日常增量更新和历史全量校准。分析侧既可以选中指定问题，也可以按筛选结果发起批量任务，并配置并发。运行中可以查看进度、重试失败项和取消任务，中断任务也有恢复机制。结果侧保留独立 AI 建议，由人工选择采纳，并支持按当前范围导出。');

  // 6. Human oversight and useful test material, without UI mockups.
  s=base(p,'AI 分析输出与人工职责','输出围绕测试准备展开，明确事实、假设和待补信息');
  text(s,'ai-col-heading','AI 辅助整理',110,300,800,65,43,C.green,true);
  text(s,'ai-col-body','中文摘要与价值判断\n复现性评估与可能根因\n模型配置、硬件和软件版本\n触发场景、预期结果与验证断言',110,409,800,340,35,C.ink);
  text(s,'human-col-heading','人工审核与决策',1060,300,750,65,43,C.green,true);
  text(s,'human-col-body','核对原文证据和关键参数\n确认缺失信息并补充材料\n验证根因与实际复现结果\n判断漏测原因和用例入库',1060,409,750,340,35,C.ink);
  line(s,102,825,1708);
  text(s,'ai-input-rule','A2 / A3 / A5、量化与并行配置仅提取原文已提供的信息，缺失项标为“待确认”。',110,859,1700,72,29,C.muted);
  notes(s,70,'AI 会整理正文和评论，输出中文摘要、价值判断、可能根因和补测建议。补测建议重点包括模型名称、精度量化、TP/PP/EP 配置，A2、A3、A5 硬件和相关软件版本，以及触发请求和验证断言。原文没有的参数要明确标为待确认。漏测原因保留人工填写，因为判断内部为什么没有测到，需要实际测试覆盖信息。人员还要核对证据、实际复现并决定是否形成回归用例。');

  // 7. A sourced example, with explicit uncertainty on the slide itself.
  s=base(p,'案例：Kimi 模型 decode 崩溃反馈','依据此前提供的反馈材料整理，根因和实际复现结果仍待核实');
  table(s,[['需要提取的内容','案例材料与下一步动作'],
    ['环境与配置','Atlas 800I A3、CANN 9.2.0\nKimi-K3 W4A8、TP16 加 EP'],
    ['报告者描述的现象','prefill 正常，decode 崩溃\nkeyRope 视图偏移非法'],
    ['待验证假设','算子内部偏移计算异常，整数溢出属于假设'],
    ['建议验证动作','补齐关键参数，复现 decode 请求\n对照 eager、图模式与不同软件环境'],
  ],{widths:[440,1270],fs:32,h:575});
  notes(s,90,'此前提供的一条反馈描述：在 CANN 9.2.0、Atlas 800I A3、TP16 加 EP 环境运行 Kimi-K3 W4A8，prefill 正常，decode 阶段出现 keyRope 视图偏移非法错误。长正文中还包含多次运行日志和执行模式对照。工具辅助提取环境配置、观察现象和验证动作。报告者认为存在整数溢出，但这仍是需要算子团队或实验验证的假设。测试人员可以据此补齐缺失参数，准备相应环境并设计对照验证。本例说明材料如何转化为测试准备输入，并不代表系统已经复现问题或确认了根因。','docs/issue-tracker项目成果汇报-15分钟版.md 第四部分，用户此前提供的 Issue #17084 分析材料');

  // 8. Explicit rule ordering, with the exclusion boundary visible.
  s=base(p,'“优先处理”的筛选与排序','为当前一批问题提供复现投入的候选顺序');
  text(s,'priority-filter-heading','入选条件',110,300,760,65,43,C.green,true);
  text(s,'priority-filter-body','有最新已保存的 AI 分析结果\n复现性和价值均为“高”或“中”\n排除 Doc、RFC、咨询与非问题',110,410,830,250,34);
  text(s,'priority-order-heading','排序顺序',1080,300,720,65,43,C.green,true);
  text(s,'priority-order-body','1   复现性\n2   价值，优先采用人工填写值\n3   明确版本的相对新旧\n4   AI 自评置信度及创建时间',1080,410,720,300,34);
  text(s,'priority-caveat','高价值但信息不足的问题也可能被隐藏，需要回到完整列表复查。',110,839,1690,80,32,C.amber);
  notes(s,70,'优先处理是一个候选视图，首先读取最新已保存的 AI 结果，保留复现性和价值为高或中的问题，并排除文档、RFC、咨询和非问题。排序先比较复现性，再比较价值，已有人工价值等级优先。之后参考明确版本的相对新旧、AI 自评置信度和创建时间。目前没有接入官方版本兼容矩阵，置信度也不是经过校准的正确率。高价值但信息不足的问题可能被隐藏，所以需要完整列表复查。');

  // 9. Evidence and benefit claims are deliberately separate.
  s=base(p,'项目收益与验证指标','当前可以确认能力已经落地，收益幅度需要持续统计');
  table(s,[['已落地的能力','预期收益','建议验证指标'],
    ['持续同步与统一台账','减少重复收集和交接整理','同步完整性、人工整理耗时'],
    ['AI 归纳与批量任务','缩短阅读与初步筛选时间','人工审核耗时、建议采纳情况'],
    ['复现候选与补测建议','支持重点问题验证和测试准备','推荐有效率、实际复现结果'],
    ['分析记录与筛选导出','积累可复用的测试输入','回归用例转化量、后续复用情况'],
  ],{widths:[530,580,600],fs:30,h:580});
  notes(s,65,'项目已经形成持续管理入口、批量辅助分析能力，以及面向测试的输出要求。对应的预期收益包括减少重复收集、缩短阅读筛选和增加测试转化机会。具体幅度要用运行数据验证，不能直接给未经验证的提升比例。统计时，应把生成建议、人工确认、实际复现和用例入库分别记录。尤其要把人工审核时间纳入效率统计，才能判断 AI 是否真正减轻了工作量。');

  // 10. Conditions under which recommendations are useful.
  s=base(p,'当前边界与使用原则','分析质量与最终测试效果，需要独立核查');
  rows(s,[
    ['复现性评价来自材料','AI 尚未执行真实环境，实际复现由人员和测试环境验证。'],
    ['版本信息需要核查','当前按明确版本辅助排序，修复状态仍需官方信息或实验确认。'],
    ['关键判断由人工负责','核查事实与假设，复查高价值信息不足的问题，确认采纳与入库。'],
  ]);
  notes(s,50,'这里明确工具的适用边界。第一，AI 对复现性的评价来自现有材料，不代表系统执行过复现。第二，版本排序没有自动验证修复状态，需要兼容信息或实验支持。第三，人工负责关键结论，同时应抽查被筛掉的高价值问题。这样既能使用自动整理能力，也能保留必要的质量判断。');

  // 11. Proposed roadmap with tangible acceptance evidence.
  s=base(p,'后续优化计划','先建立质量基线，再改进证据与规则，最后开展测试转化试点');
  table(s,[['阶段','重点工作','可验收的交付物'],
    ['01  质量评估','建议选取 50–100 条代表样本\n人工评审，并抽查被筛掉的问题','样本集、评审标准\n首轮质量基线'],
    ['02  证据与规则','补充原文依据、版本配套信息\n跟进高价值但信息不足的问题','可核查的分析材料\n规则改进与复评结果'],
    ['03  测试转化','选择环境可用的问题开展人工复现\n提炼最小用例并评审入库','复现记录、验证结论\n关联来源 Issue 的回归用例'],
  ],{widths:[330,790,590],fs:30,h:590});
  notes(s,85,'后续分三个阶段推进。第一阶段建立质量评估，建议先选择五十到一百条代表性样本，覆盖真实缺陷、文档、咨询以及不同信息完整度，交付评审标准和首轮基线。除了看推荐有效性，还要抽查被筛掉的问题。第二阶段根据结果补充原文依据和可靠版本信息，为高价值信息不足的问题提供跟进方式。第三阶段选择少量环境可用的问题，完成材料补齐、人工复现、最小用例提炼和评审入库。最终交付应能说明来源、条件、结果和测试贡献。具体门槛根据第一轮基线确定。');

  // 12. A quiet conclusion, focused on observable success criteria.
  s=base(p,'下一阶段的成功标准');
  text(s,'close-main','让值得投入的问题\n更快进入实际验证',110,278,1680,220,75,C.green,true);
  text(s,'close-evidence','人工分析更省时\n重点问题能够复现\n社区反馈形成可复用的回归测试',118,592,1580,240,40,C.ink);
  notes(s,30,'issue-tracker 已经完成了持续汇集、统一分析、批量处理和辅助筛选的工具建设。接下来，我们用更明确的业务结果检验它：分析人员能否更快找到值得投入的问题，建议能否帮助实际复现，社区反馈能否形成有效的回归测试。通过这些结果决定项目进一步优化和推广的方向。谢谢大家。');

  expandWorkflowSlide(p);
  enrichReportText(p);
  return {slideCount:p.slides.items.length,totalSpeakingSeconds:765,canvas:{width:W,height:H}};
}

export function expandWorkflowSlide(p, originalSection='') {
  const s=p.slides.items[3];
  const named=name=>{
    const shape=s.shapes.items.find(x=>x.name===name);
    if(!shape) throw new Error(`Missing workflow element: ${name}`);
    return shape;
  };
  for(let i=0;i<5;i++) {
    const x=104+i*346;
    named(`workflow-stage-${i}`).position={left:x,top:285,width:300,height:145};
    const title=named(`workflow-title-${i}`);
    title.position={left:x+22,top:301,width:256,height:45};
    title.text.style={typeface:FONT,fontSize:32,bold:true,color:C.green,insets:0,autoFit:'none'};
    const body=named(`workflow-body-${i}`);
    body.position={left:x+22,top:357,width:256,height:65};
    body.text.style={typeface:FONT,fontSize:25,color:C.ink,insets:0,autoFit:'none'};
  }
  const explanations=[
    ['持续更新的问题台账','首次全量、默认每 15 分钟增量同步与手动校准，社区信息和人工分析分别维护。'],
    ['统一的分析入口','按日期、状态、标签、价值和版本筛选，统一记录分析、补测、支持及闭环状态，并支持导出。'],
    ['AI 分析与人工审核','结合正文与评论生成结构化建议，人工检查后采纳，区分事实与推测，漏测原因由人工填写。'],
    ['可跟踪的批量任务','勾选或按筛选结果批量分析，支持并发、进度、重试、取消及服务重启后恢复。'],
    ['复现候选清单','保留复现性与价值均为高或中的问题，排除 Doc/RFC 等类型，按复现性、价值及明确版本信息排序。'],
  ];
  explanations.forEach(([heading,body],i)=>{
    const y=480+i*90;
    const labelText=`${String(i+1).padStart(2,'0')}  ${heading}`;
    if(i===0){
      const label=named('workflow-followup-title');
      label.position={left:112,top:y,width:430,height:76}; label.text=labelText;
      label.text.style={typeface:FONT,fontSize:30,bold:true,color:C.green,insets:0,autoFit:'none'};
      const detail=named('workflow-followup');
      detail.position={left:560,top:y,width:1240,height:78}; detail.text=body;
      detail.text.style={typeface:FONT,fontSize:29,color:C.ink,insets:0,autoFit:'none'};
    }else{
      text(s,`workflow-explain-label-${i}`,labelText,112,y,430,76,30,C.green,true);
      text(s,`workflow-explain-body-${i}`,body,560,y,1240,78,29,C.ink);
    }
    if(i<4) line(s,112,y+78,1688,C.line,1);
  });
  notes(s,85,'本页对应报告第三部分的五项已完成成果。持续更新的问题台账通过首次全量、日常增量和手动校准维护社区数据，同时保留人工分析。统一入口支持按多维度筛选，并记录问题分析、补测、版本支持及闭环状态。AI 结合正文与评论生成结构化建议，由人工核查后采纳，信息不足时明确缺口，漏测原因由人工填写。批量任务支持勾选或按筛选范围创建，可配置并发、查看进度、重试和取消，并在服务重启后恢复中断任务。优先处理视图为复现工作提供候选清单，复现性和价值主要来自 AI 判断，价值优先采用人工填写值，版本信息辅助排序。后续仍需用人工核验结果校准推荐效果。'+(originalSection?'\n\n报告第三部分完整原文：\n'+originalSection:''));
  return {updatedSlide:4,explanationCount:5};
}

export function enrichReportText(p) {
  const get=(index,name)=>{
    const shape=p.slides.items[index-1].shapes.items.find(x=>x.name===name);
    if(!shape) throw new Error(`Missing slide ${index} element ${name}`);
    return shape;
  };
  const change=(index,name,value,position,size)=>{
    const shape=get(index,name);
    shape.text=value;
    if(position) shape.position=position;
    if(size) shape.text.style={typeface:FONT,fontSize:size,color:C.ink,insets:0,wrap:'square',autoFit:'none'};
  };
  const rewriteTable=(index,values,fs=29)=>{
    const t=p.slides.items[index-1].tables.items[0];
    values.forEach((row,r)=>row.forEach((value,c)=>{
      const cell=t.getCell(r,c); cell.value=value;
      cell.text.style={typeface:FONT,fontSize:r===0?fs+2:fs,bold:r===0,color:r===0?C.white:C.ink,wrap:'square',autoFit:'none',verticalAlignment:'middle'};
    }));
  };

  change(2,'row-0-body','新增 Issue、历史评论和状态变化需要反复核对。关键日志和解决进展分散在不同位置，专项分析中断后往往需要重新整理材料。');
  change(2,'row-1-body','真实缺陷、文档和使用咨询混杂。模型、量化、并行方式与版本组合复杂，需要先判断问题价值和复现条件，再分配测试资源。');
  change(2,'row-2-body','结论分散在个人表格和文档中，问题是否分析过、缺少哪些材料、需要补什么测试难以统一查看，交接时容易重复阅读。');

  rewriteTable(5,[
    ['工作环节','已实现能力','对实际工作的作用'],
    ['数据同步','首次全量、默认 15 分钟增量同步与手动校准\n社区侧信息与本地人工分析分别维护','跟进新增与历史更新\n在信息更新时保留分析积累'],
    ['批量分析','支持勾选指定 Issue 或按筛选结果创建任务\n可配置并发，支持跳过相同输入的已有分析','集中梳理一批问题\n减少重复提交和等待操作'],
    ['任务运行','任务进度、失败重试、取消与中断恢复\n任务及结果持久保存，重启后恢复处理','查看处理状态和失败项\n支持长时间运行的分析工作'],
    ['结果管理','AI 建议独立保存，人工审核后采纳\n统一记录分析状态，按筛选范围导出 Excel','便于阶段评审与团队交接\n在已有结论上继续开展分析'],
  ]);
  text(p.slides.items[4],'expanded-capability-note','工作范围：只读获取社区问题，本地维护分析记录与建议采纳结果。',112,903,1690,55,27,C.muted);

  change(6,'ai-col-body','摘要与识别：归纳问题现象、来源和价值，说明判断依据。\n\n复现与补测：整理模型、硬件、版本、触发场景及验证断言。\n\n信息缺口：标明缺失参数，区分已知事实与根因假设。',{left:110,top:405,width:800,height:390},32);
  change(6,'human-col-body','证据核查：对照正文和评论，检查关键配置与建议是否可靠。\n\n分析确认：检查后选择采纳，结合实际覆盖填写漏测原因。\n\n测试决策：补齐材料、执行复现，评审根因与用例入库。',{left:1060,top:405,width:750,height:390},32);

  rewriteTable(7,[
    ['需要提取的内容','案例材料与下一步动作'],
    ['环境与配置','报告者提供 Atlas 800I A3、CANN 9.2.0 环境\n模型为 Kimi-K3 W4A8，并行方式为 TP16 加 EP'],
    ['报告者描述的现象','prefill 正常，decode 出现 keyRope 视图偏移非法错误\n反馈还包含多次运行日志和执行模式的对照现象'],
    ['待验证假设','算子内部偏移计算异常属于可能原因\n整数溢出需要代码或实验依据进一步确认'],
    ['建议验证动作','补齐参数，准备相应环境并复现 decode 请求\n对照 eager、图模式和不同软件环境，记录错误与运行结果'],
  ],30);
  text(p.slides.items[6],'expanded-case-note','案例作用：把长篇反馈整理为可核查的配置、现象和验证动作，支持测试人员继续推进。',112,902,1690,58,27,C.muted);

  change(8,'priority-filter-body','分析依据：最新已保存的 AI 分析结果。\n\n纳入范围：复现性和价值均为“高”或“中”。\n\n排除范围：Doc、RFC、咨询与非问题。\n\n人工优先：价值等级采用已有人工填写值。',{left:110,top:410,width:830,height:370},31);
  change(8,'priority-order-body','1   复现性，高优先于中\n\n2   价值，高优先于中\n\n3   明确版本在候选中的相对新旧\n\n4   AI 自评置信度、创建时间及编号',{left:1080,top:410,width:720,height:370},31);
  change(8,'priority-caveat','列表工具栏勾选“优先处理”，即可查看排名与推荐理由。高价值但信息不足的问题也可能被隐藏，需要回到完整列表复查。',{left:110,top:839,width:1690,height:90},30);

  rewriteTable(9,[
    ['已落地的能力','预期收益','建议验证指标'],
    ['持续同步与统一台账','减少重复收集与核对\n让专题分析基于已有积累继续开展','同步完整性、人工整理耗时\n核对同仓库、同时间与同筛选范围'],
    ['AI 归纳与批量任务','减少初步阅读和资料整理投入\n把人工精力集中到审核与验证','人工审核耗时、建议采纳情况\n比较相近复杂度的分析样本'],
    ['复现候选与补测建议','收敛重点问题范围\n明确测试准备需要的配置与材料','推荐有效性、实际复现结果\n同时抽查被筛掉的重要问题'],
    ['分析记录与筛选导出','便于共享、交接和专题评审\n沉淀可复用的测试输入','回归用例转化量、后续复用\n保留 Issue 与用例的关联记录'],
  ],28);
  text(p.slides.items[8],'expanded-metric-note','统计口径：AI 生成、人工确认、实际复现与用例入库分别统计，审核耗时计入效率评价。',112,903,1690,55,27,C.muted);

  change(10,'row-0-body','AI 根据步骤、配置和日志评价复现性，尚未执行真实环境。自评置信度也不能直接当作经过人工评估的准确率。');
  change(10,'row-1-body','当前排序参考候选中的明确版本，尚未接入官方兼容矩阵。是否配套、是否修复，需要官方信息或实际对照实验确认。');
  change(10,'row-2-body','人员负责核查事实与假设、补齐关键材料，并决定采纳和入库。完整列表保留原始问题，便于复查高价值但信息不足的反馈。');

  rewriteTable(11,[
    ['阶段','重点工作','可验收的交付物'],
    ['01  质量评估','建议选取 50–100 条代表样本\n覆盖缺陷、咨询及不同信息完整度\n人工评审，并抽查被筛掉的问题','样本集、评审标准与首轮基线\n评估摘要、参数准确性及建议可执行性\n据此确定下一轮验收门槛'],
    ['02  证据与规则','补充原文依据与可靠版本配套信息\n明确分析缺口，跟进高价值信息不足问题\n结合评审结果迭代提示词与筛选规则','可核查的证据与缺口说明\n规则改进记录和样本复评结果\n逐步关联 PR、修复记录与内部用例'],
    ['03  测试转化','选择少量价值明确、环境可用的问题\n补齐材料并开展人工复现\n提炼最小用例，完成评审与入库','来源 Issue、配置与复现结果\n最小用例和评审记录\n跟踪回归效果，判断是否扩大试点'],
  ],28);
  text(p.slides.items[10],'expanded-roadmap-note','推进原则：先验证分析质量与测试收益，再根据使用人数和数据规模完善协作、权限与基础设施。',112,908,1690,52,26,C.muted);

  change(12,'close-main','让值得投入的问题\n更快进入实际验证',{left:110,top:278,width:1680,height:220},70);
  get(12,'close-main').text.style={typeface:FONT,fontSize:70,color:C.green,bold:true,insets:0,autoFit:'none'};
  change(12,'close-evidence','效率：把人工审核时间纳入统计，确认资料整理与筛选投入是否下降。\n\n质量：记录推荐有效性和实际复现结果，并复查被筛掉的重要问题。\n\n转化：关联来源 Issue、最小复现条件和回归用例，跟踪后续复用。',{left:118,top:570,width:1580,height:300},34);
  text(p.slides.items[11],'expanded-close-next','下一步先建立评审基线，再用少量高价值问题验证实际测试贡献。',118,888,1580,58,29,C.muted);

  refineReadingLayout(p);
  return {slides:p.slides.items.length,enrichedSlides:[2,5,6,7,8,9,10,11,12],workflowRetained:true};
}

export function refineReadingLayout(p) {
  const updates=[
    [2,'row-0-body','新增 Issue、历史评论和状态变化需要反复核对，关键日志和解决进展也分散在不同位置。\n专项分析中断后，分析人员往往需要重新整理材料。'],
    [2,'row-1-body','真实缺陷、文档和使用咨询混杂，模型、量化、并行方式与版本组合复杂。\n分析人员需要先判断问题价值和复现条件，再分配测试资源。'],
    [2,'row-2-body','已有结论分散存放，分析进展、材料缺口和补测需求难以统一查看。\n团队交接和后续复查时，容易重复阅读相同材料。'],
    [6,'ai-col-body','摘要与识别：归纳问题现象、来源和价值，\n说明判断依据。\n\n复现与补测：整理模型、硬件、版本、\n触发场景及验证断言。\n\n信息缺口：标明缺失参数，区分已知事实\n与根因假设。'],
    [6,'human-col-body','证据核查：对照正文和评论，检查关键配置\n与建议是否可靠。\n\n分析确认：检查后选择采纳，结合实际覆盖\n填写漏测原因。\n\n测试决策：补齐材料、执行复现，评审根因\n与用例入库。'],
    [10,'row-0-body','AI 根据步骤、配置和日志评价复现性，尚未执行真实环境。\n模型自评置信度需独立核验，不能作为人工评估的准确率。'],
    [10,'row-1-body','当前排序参考候选中的明确版本，尚未接入官方兼容矩阵。\n版本是否配套、问题是否修复，需要官方信息或实际对照实验确认。'],
    [10,'row-2-body','人员负责核查事实与假设、补齐关键材料，并决定采纳和入库。\n完整列表保留原始问题，便于复查高价值但信息不足的反馈。'],
  ];
  updates.forEach(([index,name,value])=>{
    const shape=p.slides.items[index-1].shapes.items.find(x=>x.name===name);
    if(!shape) throw new Error(`Missing slide ${index} element ${name}`);
    shape.text=value;
  });
  return {refinedSlides:[2,6,10]};
}
