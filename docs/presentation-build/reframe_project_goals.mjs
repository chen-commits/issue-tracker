const FONT='Microsoft YaHei';
const C={ink:'#21372F',green:'#227451',muted:'#60756B',line:'#D5E2DA',white:'#FFFFFF'};
function text(s,name,value,x,y,w,h,size=32,color=C.ink,bold=false,align='left'){
  const a=s.shapes.add({name,geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
  a.text=value;
  a.text.style={typeface:FONT,fontSize:size,color,bold,alignment:align,insets:0,wrap:'square',autoFit:'none'};
  return a;
}
function formatTable(t,values,widths,{top=300,height=580,header=88,fs=28,margin=18}={}){
  if(values.length>t.rows.length) t.insertRows({index:t.rows.length,count:values.length-t.rows.length});
  t.columnWidths=widths;
  widths.forEach((w,i)=>{t.columns.get(i).width=w;});
  t.cells.block({row:0,column:0,rowCount:values.length,columnCount:values[0].length}).assign({margins:{top:margin,bottom:margin,left:20,right:20}});
  t.borders.assign({fill:C.line,width:1,style:'solid'});
  values.forEach((row,r)=>{
    t.rows[r].height=r===0?header:(height-header)/(values.length-1);
    row.forEach((v,c)=>{
      const cell=t.getCell(r,c);cell.value=v;cell.fill=r===0?C.green:C.white;
      cell.text.style={typeface:FONT,fontSize:r===0?fs+2:fs,bold:r===0,color:r===0?C.white:C.ink,insets:0,verticalAlignment:'middle',autoFit:'none',wrap:'square'};
    });
  });
}
function setNotes(s,seconds,body){
  s.speakerNotes.text=`建议讲述时长：${seconds} 秒。\n\n${body}\n\n依据：项目报告、鱼骨图及项目功能说明。各项能力统一作为整体目标的解决方案介绍，评价指标用于观察效果，未引用未经统计的收益数字。`;
}
export function reframeProjectGoals(p){
  const original=[...p.slides.items];
  if(original.length!==12)throw new Error('Expected the existing 12-slide deck');
  const named=(index,name)=>{
    const v=original[index-1].shapes.items.find(x=>x.name===name);
    if(!v)throw new Error(`Missing slide ${index} ${name}`);
    return v;
  };
  const replace=(i,name,value)=>{named(i,name).text=value;};
  replace(1,'cover-title','项目目标与解决方案');
  setNotes(original[0],25,'今天介绍 issue-tracker 的整体目标和解决方案。汇报围绕社区问题持续跟踪、分析投入选择和经验复用等痛点展开，并说明统一台账、人工分析、批量任务和 AI 辅助怎样共同服务于项目目标。');

  replace(4,'slide-title','项目整体工作流程');
  replace(4,'slide-subtitle','通过统一台账串联问题跟踪、分析筛选、人工审核与结果沉淀');
  setNotes(original[3],75,'项目整体工作流程包含同步汇集、范围筛选、AI 辅助分析、人工审核和分析沉淀。全量与增量同步结合手动校准，持续维护社区信息，并保留本地人工分析。统一入口按日期、状态、标签、价值和版本收敛范围，记录补测及处理状态。AI 结合正文与评论提供结构化建议，由人员检查采纳，漏测原因结合实际测试覆盖人工填写。批量任务支持选中或按筛选范围创建，结合并发、进度、重试和恢复支持集中梳理。候选筛选把较可复现且有价值的问题送到重点验证范围。');

  replace(5,'slide-title','痛点与解决方案');
  replace(5,'slide-subtitle','对应鱼骨图六类影响因素，说明项目的处理方式与期望作用');
  const painTable=original[4].tables.items[0];
  formatTable(painTable,[
    ['痛点类别','解决方案','期望作用'],
    ['信息获取','全量与增量同步结合手动校准\n建立统一问题入口，持续跟进变化','减少分散查找与反复核对\n关注同步完整性和更新及时性'],
    ['分析方法','多维筛选与统一分析字段\n结合人工和 AI 判断价值、复现性与重点','统一分析口径和关注范围\n把投入集中到值得验证的问题'],
    ['环境配置','整理模型、量化、并行、硬件和软件版本\n明确触发场景、验证条件与待补参数','支持复现环境与测试准备\n提高材料完整性和可核查性'],
    ['人员协作','统一记录问题识别、结论和处理状态\n通过评审导出与台账记录支持交接','便于接续分析和协同跟进\n减少重复阅读与信息断层'],
    ['工作流程','选中或按筛选范围创建批量任务\n结合进度、重试、人工审核与状态维护','减少逐条提交与整理操作\n集中查看任务和结果'],
    ['知识沉淀','保存人工分析与 AI 建议\n整理典型场景及相关测试验证材料','支持同类问题经验复用\n促进社区反馈转化为测试输入'],
  ],[290,810,610],{height:620,header:74,fs:26,margin:12});
  painTable.position={left:104,top:260,width:1710,height:620};
  const scope=named(5,'expanded-capability-note');
  scope.position={left:112,top:925,width:1690,height:34};
  scope.text='方案围绕具体工作痛点组织，统一台账和人工分析提供基础，AI 辅助归纳与筛选。';
  scope.text.style={typeface:FONT,fontSize:24,color:C.muted,insets:0,autoFit:'none'};
  setNotes(original[4],90,'这一页逐项对应鱼骨图。信息获取用持续同步和统一入口解决。分析方法用多维筛选、统一字段和人工加 AI 辅助判断，明确分析重点。环境配置通过提取模型、硬件、软件及触发条件帮助测试准备。人员协作依托台账、状态记录和评审导出，方便交接。工作流程通过批量任务、进度和重试支持集中梳理。知识沉淀则保存分析与典型场景，支持后续复用。这里统一介绍项目针对痛点的解决方案，预期作用通过后续指标和案例观察。');

  replace(9,'slide-title','项目价值与评价指标');
  replace(9,'slide-subtitle','围绕资料整理效率、分析质量和测试转化，持续观察方案效果');
  original[8].tables.items[0].getCell(0,0).value='解决方案';
  original[8].tables.items[0].getCell(0,1).value='期望作用';
  original[8].tables.items[0].getCell(0,2).value='评价关注点';
  setNotes(original[8],60,'项目价值围绕整体目标衡量。持续同步与统一台账关注资料整理和交接投入。人工与 AI 辅助分析关注阅读筛选和审核时间。复现候选与补测建议关注推荐有效性和实际验证结果。结果沉淀关注测试用例转化与后续复用。统计时把建议生成、人工确认、实际复现和用例入库分别记录，避免把过程数量当成最终收益。');

  replace(10,'slide-title','方案应用与质量控制');
  replace(10,'slide-subtitle','以证据核查和人工审核保障分析与测试决策的可靠性');
  replace(10,'row-0-heading','分析结论有据可查');
  replace(10,'row-0-body','分析结合正文、评论、配置和日志，区分事实、假设与缺失信息。\n复现性判断和 AI 自评置信度，通过人工抽检与实验结果核验。');
  replace(10,'row-1-heading','环境与版本逐项核实');
  replace(10,'row-1-body','明确模型配置、硬件环境、软件版本和触发条件，整理需要补采的参数。\n版本配套与修复结论结合可靠资料和实际对照验证确认。');
  replace(10,'row-2-heading','人员负责关键决策');
  replace(10,'row-2-body','人员核查证据、补齐材料并决定采纳与测试入库，漏测原因结合实际覆盖填写。\n保留完整问题列表，并复查高价值但信息不足的反馈，减少筛选遗漏。');
  setNotes(original[9],45,'质量控制贯穿方案应用。分析材料应说明事实、假设与信息缺口，重要判断需要有原文或实验支持。模型、硬件、版本和触发条件逐项核实，缺失项补采。人工审核负责采纳、根因确认和测试决策，并复查高价值但信息不足的问题。AI 辅助判断的效果通过样本评审和实际复现结果验证。');

  replace(11,'slide-title','目标推进与持续改进');
  replace(11,'slide-subtitle','围绕分析质量、证据与规则、测试转化设置改进方向');
  const roadmap=original[10].tables.items[0];
  roadmap.getCell(0,0).value='改进方向';roadmap.getCell(0,1).value='解决方案';roadmap.getCell(0,2).value='评价与产出';
  roadmap.getCell(1,0).value='分析质量';roadmap.getCell(2,0).value='证据与规则';roadmap.getCell(3,0).value='测试转化';
  replace(11,'expanded-roadmap-note','持续改进依据人工评审与测试结果展开，同时关注运行成本、任务稳定性和团队使用体验。');
  setNotes(original[10],65,'整体目标通过持续改进推进。分析质量方面建议选取代表性样本，覆盖缺陷、咨询和不同材料完整度，形成人工评审基线。证据与规则方面补充原文依据和可靠配套信息，并用复评结果改进提示词与筛选方式。测试转化方面选择价值明确、环境可用的问题补齐材料，开展人工复现，形成最小用例及评审记录。根据实际结果持续调整方案，也关注成本和任务稳定性。');

  replace(12,'slide-title','项目目标与价值总结');
  replace(12,'close-main','持续跟踪社区问题\n支撑测试分析与经验复用');
  replace(12,'close-evidence','管理目标：集中维护问题信息、分析结论和处理进展，支持专项筛选与协作交接。\n\n分析目标：结合人工判断与 AI 辅助，提取关键配置、信息缺口和可验证的测试建议。\n\n测试目标：将值得投入的问题整理成测试输入，推动实际验证、场景积累与回归用例复用。');
  replace(12,'expanded-close-next','项目价值通过分析投入、推荐质量、实际验证结果和测试材料复用持续评价。');
  setNotes(original[11],25,'项目整体目标是持续跟踪社区问题，支撑测试分析与经验复用。管理上集中维护数据和进展。分析上结合人工判断和 AI 辅助，整理配置、缺口及测试建议。测试上把值得投入的问题转化为可验证的场景与可复用材料。最终通过实际工作投入和测试贡献评价项目价值。谢谢大家。');

  const goal=p.slides.add({width:1920,height:1080});
  goal.background.fill=C.white;
  text(goal,'slide-title','整体目标设定',100,76,1700,105,57,C.ink,true);
  text(goal,'slide-subtitle','建立面向社区 Issue 的持续跟踪与测试分析平台',104,187,1680,70,32,C.muted);
  const gt=goal.tables.add({rows:5,columns:3,left:104,top:300,width:1710,height:580,columnWidths:[330,840,540],values:[['','',''],['','',''],['','',''],['','',''],['','','']]});
  formatTable(gt,[
    ['目标方向','项目目标','评价关注点'],
    ['持续跟踪','集中获取和更新社区问题\n形成可筛选、可持续维护的统一台账','信息覆盖与更新及时性\n专题资料整理投入'],
    ['重点投入','围绕版本、标签、价值与复现条件收敛范围\n帮助分析人员选择值得验证的问题','筛选效率与推荐有效性\n重要问题的遗漏情况'],
    ['分析复用','统一记录人工结论、补测建议和处理进展\n让交接、评审和同类问题分析能够复用','记录完整性和交接效率\n已有分析与典型场景复用'],
    ['测试改进','人工判断结合 AI 辅助归纳\n将问题反馈整理为复现材料与测试输入','建议可执行性与验证结果\n测试用例转化及回归贡献'],
  ],[330,840,540],{height:580,header:88,fs:28,margin:16});
  text(goal,'goal-summary','统一台账与人工分析构成基础，AI 辅助服务于信息归纳、候选筛选和测试准备。',112,913,1690,46,27,C.muted);
  goal.shapes.add({geometry:'line',position:{left:100,top:972,width:1720,height:0},line:{fill:C.line,width:2},fill:'none'});
  text(goal,'footer','issue-tracker 项目汇报',104,998,1350,35,22,C.muted);
  text(goal,'page-number','04',1710,994,100,40,24,C.muted,false,'right');
  setNotes(goal,65,'整体目标分为四个方向。持续跟踪强调统一获取与维护社区信息，减少重新收集。重点投入强调围绕版本、标签、价值和复现条件收敛范围，帮助人员选择值得验证的问题。分析复用强调保存人工结论、补测建议和处理进展，支撑交接与同类问题复查。测试改进强调人工判断结合 AI 辅助，把社区反馈整理为测试输入。各项能力统一组织在整体目标下，通过实际工作和测试结果评价方案效果。');
  p.slides.reorder([...original.slice(0,3),goal,...original.slice(3)].map(s=>`sl/${s.id}`));
  p.slides.items.forEach((s,i)=>{
    const page=s.shapes.items.find(x=>x.name==='page-number');if(page)page.text=String(i+1).padStart(2,'0');
    const footer=s.shapes.items.find(x=>x.name==='footer');if(footer)footer.text='issue-tracker 项目汇报';
  });
  return {slides:p.slides.items.length,goalsSlide:4,painSolutionSlide:6,aiRetained:true};
}
