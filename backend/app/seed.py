"""Idempotent development/demo/E2E seed. The password must come from the environment."""
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import or_, select

from .database import SessionLocal
from .models import (
    AuditLogModel,
    DepartmentModel,
    KbChunkModel,
    KbDocumentModel,
    KbEvalCaseModel,
    TicketModel,
    TicketStatusHistoryModel,
    UserModel,
    WorkOrderModel,
)
from .security import hash_password


DEPARTMENTS = (
    ("urban-management", "城市管理", "市容、环卫、道路与公共设施"),
    ("transport", "交通运输", "公交、道路运输与交通服务"),
    ("housing-property", "住房物业", "住房、物业与小区管理"),
    ("education", "教育服务", "学校与教育公共服务"),
    ("health", "医疗卫生", "医疗与公共卫生服务"),
    ("community-civil", "社区民政", "社区、养老与民政服务"),
    ("general-intake", "综合受理", "跨部门事项与统一受理"),
)
USERS = (
    ("citizen_local", "演示市民", "citizen", None),
    ("agent_local", "演示坐席", "agent", None),
    ("department_local", "演示部门人员", "department_staff", "general-intake"),
    ("admin_local", "演示管理员", "admin", None),
)

# Issuing authority per seed_key. The KB_DOCUMENTS tuple structure is unchanged;
# this map supplies issuing_authority at seed time so citations expose the
# publishing body without touching raw_content.
ISSUING_AUTHORITY_MAP = {
    "kb_policy_lighting": "市城市管理行政执法局",
    "kb_guide_lighting_report": "市城市管理行政执法局",
    "kb_faq_lighting": "市城市管理行政执法局",
    "kb_policy_transport": "市交通运输局",
    "kb_policy_housing_fee": "市住房和城乡建设局",
    "kb_guide_id_card": "市公安局",
    "kb_policy_social_security_subsidy": "市人力资源和社会保障局",
    "kb_policy_compulsory_education": "市教育局",
    "kb_guide_housing_fund_extraction": "市住房公积金管理中心",
    "kb_guide_lowest_living_security": "市民政局",
    "kb_policy_expired_trash": "市城市管理行政执法局",
}

# Demo knowledge base documents. (key, title, doc_number, dept_code, kb_type, domain, region,
# audience, visibility, file_type, keywords, effective_days_ago, expires_after_days, raw_content)
# expires_after_days=None means no expiry; negative number means already expired.
KB_DOCUMENTS = (
    (
        "kb_policy_lighting",
        "城市道路照明管理办法",
        "市政发〔2024〕12号",
        "urban-management",
        "policy",
        "市政设施",
        "全市",
        "全体市民",
        "PUBLIC",
        "markdown",
        "路灯,照明,道路照明,市政设施,路灯维修",
        365,
        None,
        """# 城市道路照明管理办法

## 第一章 总则

第一条 为加强城市道路照明管理，保障市民夜间出行安全，根据《城市市容和环境卫生管理条例》，结合本市实际，制定本办法。

第二条 本办法适用于本市行政区域内城市道路照明设施的规划、建设、维护和监督管理。

第三条 市城市管理行政主管部门负责全市道路照明设施的统一监督管理；区县城市管理部门负责本辖区内道路照明设施的日常维护。

## 第二章 维护责任

第四条 道路照明设施由市、区县城市管理部门按照职责分工负责维护。住宅小区内部道路照明由物业服务企业负责维护。

第五条 道路照明设施出现故障或者损毁的，维护单位应当在接到报告或者发现故障后24小时内进行现场勘查，并按照下列时限完成修复：

（一）主干道路灯故障：48小时内修复；
（二）次干道路灯故障：72小时内修复；
（三）支路及小区路灯故障：5个工作日内修复。

第六条 因恶劣天气、地下管线故障等客观原因不能按期修复的，维护单位应当向所在地城市管理部门报告并向社会公告。

## 第三章 报修与投诉

第七条 市民发现路灯故障可以通过下列方式报修：

（一）拨打12345政务服务便民热线；
（二）通过"倾听助手"平台提交诉求；
（三）向所在社区居委会反映。

第八条 城市管理部门接到路灯故障报修后，应当在2个工作日内将办理情况反馈报修人；不能按期修复的，应当说明原因并告知预计修复时间。

## 第四章 法律责任

第九条 单位或者个人损毁道路照明设施的，应当依法承担赔偿责任；构成犯罪的，依法追究刑事责任。

第十条 城市管理部门工作人员在道路照明管理工作中玩忽职守、滥用职权、徇私舞弊的，依法给予处分。

## 第五章 附则

第十一条 本办法自发布之日起施行，有效期5年。

发布单位：市城市管理行政执法局
发布日期：2024年1月15日
""",
    ),
    (
        "kb_guide_lighting_report",
        "路灯故障报修办事指南",
        "市政服〔2024〕03号",
        "urban-management",
        "guide",
        "市政设施",
        "全市",
        "全体市民",
        "PUBLIC",
        "markdown",
        "路灯报修,办事指南,市政服务,故障申报",
        300,
        None,
        """# 路灯故障报修办事指南

## 一、适用范围

本指南适用于市民反映城市道路（含主干路、次干路、支路）路灯不亮、闪烁、损毁等故障问题的报修办理。

## 二、受理对象

本市行政区域内的全体市民、企事业单位和社会组织。

## 三、办理条件

无需特殊资格条件。市民发现路灯故障即可报修，需提供：

1. 故障路灯的具体位置（道路名称、门牌号或附近标志物）；
2. 故障现象描述（不亮/闪烁/损毁/歪斜等）；
3. 报修人联系方式（用于回访）。

## 四、申请材料

1. 报修信息（口头或书面描述均可）；
2. 现场照片（可选，有助于加快定位）。

## 五、办理流程

1. **受理**：通过12345热线、"倾听助手"平台或社区居委会受理报修。
2. **派发**：城市管理部门将工单派发至辖区路灯维护单位。
3. **修复**：维护单位按照《城市道路照明管理办法》规定的时限完成修复。
4. **反馈**：办理结果通过原渠道反馈报修人。

## 六、办理时限

- 主干道路灯：48小时内修复
- 次干道路灯：72小时内修复
- 支路及小区路灯：5个工作日内修复

## 七、办理部门

- 责任部门：市城市管理行政执法局
- 联系电话：12345
- 线上渠道：倾听助手平台 / 12345微信小程序

## 八、注意事项

- 因停电、地下管线故障等客观原因无法立即修复的，维护单位将告知预计修复时间。
- 故障涉及小区内部路灯的，由物业服务企业负责，可向物业或住建部门反映。
- 紧急情况（如路灯杆倾斜可能倒塌、漏电等）请立即拨打110或119。
""",
    ),
    (
        "kb_faq_lighting",
        "路灯故障常见问题解答",
        "",
        "urban-management",
        "faq",
        "市政设施",
        "全市",
        "全体市民",
        "PUBLIC",
        "markdown",
        "路灯,常见问题,FAQ,问答,市政",
        200,
        None,
        """# 路灯故障常见问题解答（FAQ）

### Q1：我家楼下路灯坏了，应该找谁报修？

A：可以拨打12345政务服务便民热线，或通过"倾听助手"平台提交诉求，也可以向所在社区居委会反映。城市管理部门将派人修复。

### Q2：路灯不亮一般多长时间能修好？

A：根据《城市道路照明管理办法》规定，主干道路灯48小时内修复，次干道路灯72小时内修复，支路及小区路灯5个工作日内修复。

### Q3：小区内部的路灯坏了归谁管？

A：住宅小区内部道路照明由物业服务企业负责维护。市民可向物业反映；物业公司不处理的，可向住建部门或街道办事处投诉。

### Q4：路灯杆歪了有危险，怎么办？

A：属于紧急情况，请立即拨打110或119，避免发生倒塌伤人事故。同时也可通过倾听助手平台提交紧急诉求。

### Q5：报修后长时间没有修复，如何投诉？

A：超过规定时限未修复的，可再次通过12345热线或倾听助手平台反映，城市管理部门将核查原因并督促整改。

### Q6：路灯太亮影响睡眠，可以申请调整吗？

A：可以。市民可向城市管理部门反映，工作人员将实地评估，对光照角度或灯泡功率进行调整。

### Q7：路灯电费由谁承担？

A：城市道路路灯电费由财政承担，市民无需承担。住宅小区内部路灯电费按物业服务合同约定执行。
""",
    ),
    (
        "kb_policy_transport",
        "城市公共交通乘车守则",
        "交运发〔2024〕21号",
        "transport",
        "policy",
        "公共交通",
        "全市",
        "全体市民",
        "PUBLIC",
        "markdown",
        "公交,乘车,公共交通,守则,交通运输",
        365,
        None,
        """# 城市公共交通乘车守则

## 第一章 总则

第一条 为规范城市公共交通乘车秩序，保障乘客和运营企业的合法权益，制定本守则。

第二条 本守则适用于本市行政区域内公共汽电车、轨道交通等城市公共交通工具的乘车活动。

## 第二章 乘车规则

第三条 乘客应当遵守下列规定：

（一）按顺序上下车，先下后上，不得拥挤；
（二）主动购票或刷卡，接受运营企业查验票务；
（三）老、幼、病、残、孕乘客优先乘车，其他乘客应当让座；
（四）不得在车厢内吸烟、随地吐痰、乱扔废弃物；
（五）不得携带易燃、易爆、有毒、有放射性等危险物品乘车；
（六）不得携带犬只等动物乘车（导盲犬除外）。

第四条 乘客携带物品应当符合下列规定：

（一）物品重量不超过20公斤，体积不超过0.125立方米；
（二）物品长度不超过1.8米；
（三）每名乘客携带物品不超过2件。

## 第三章 投诉与处理

第五条 乘客对运营服务不满意的，可以通过12345热线或"倾听助手"平台投诉。交通运输主管部门应当在5个工作日内予以答复。

第六条 乘客违反乘车规定的，运营企业工作人员有权劝阻；情节严重的，由公安机关依法处理。

## 第四章 附则

第七条 本守则自发布之日起施行。

发布单位：市交通运输局
发布日期：2024年3月1日
""",
    ),
    (
        "kb_policy_housing_fee",
        "物业服务收费管理办法",
        "住建发〔2024〕09号",
        "housing-property",
        "policy",
        "住房物业",
        "全市",
        "全体市民",
        "PUBLIC",
        "markdown",
        "物业费,物业服务,收费,住房,物业管理",
        300,
        None,
        """# 物业服务收费管理办法

## 第一章 总则

第一条 为规范物业服务收费行为，维护业主和物业服务企业的合法权益，制定本办法。

第二条 本办法适用于本市行政区域内物业服务收费及监督管理活动。

第三条 物业服务收费应当遵循合理、公开、费用与服务水平相适应的原则。

## 第二章 收费标准

第四条 物业服务收费根据物业的性质和特点分别实行政府指导价和市场调节价：

（一）普通住宅前期物业服务收费实行政府指导价；
（二）非普通住宅及业主大会成立后的物业服务收费实行市场调节价。

第五条 物业服务收费应当明码标价。物业服务企业应当在物业管理区域内的显著位置公示服务内容、服务标准、收费标准等项目。

第六条 物业服务费按月收取，预收期限不得超过6个月。

## 第三章 业主权利

第七条 业主对物业服务收费有异议的，可以要求物业服务企业说明收费标准和服务内容；认为收费不合理的，可以向所在区县住房城乡建设主管部门投诉。

第八条 物业服务企业未按合同约定提供服务的，业主可以依法拒付相应部分的物业服务费用。

## 第四章 投诉处理

第九条 业主就物业服务收费问题向12345热线或"倾听助手"平台投诉的，住房城乡建设主管部门应当在7个工作日内予以答复，并可以根据需要进行调解。

## 第五章 附则

第十条 本办法自发布之日起施行。

发布单位：市住房和城乡建设局
发布日期：2024年2月10日
""",
    ),
    (
        "kb_policy_expired_trash",
        "城市生活垃圾分类管理办法（2020年版）",
        "市政发〔2020〕15号",
        "urban-management",
        "policy",
        "环境卫生",
        "全市",
        "全体市民",
        "PUBLIC",
        "markdown",
        "垃圾分类,旧版,已失效,环境卫生",
        1825,
        -30,  # already expired 30 days ago
        """# 城市生活垃圾分类管理办法（2020年版）

**注：本办法已于2025年12月被《城市生活垃圾分类管理条例》取代，本办法已失效。**

## 第一章 总则

第一条 为加强城市生活垃圾分类管理，改善人居环境，制定本办法。

## 第二章 分类标准

第二条 生活垃圾分为下列四类：

（一）可回收物；
（二）有害垃圾；
（三）厨余垃圾；
（四）其他垃圾。

第三条 居民应当按照分类标准将生活垃圾分类投放至相应的收集容器。

## 第三章 附则

本办法自2020年6月1日起施行，有效期5年。

发布单位：市城市管理行政执法局
发布日期：2020年5月20日
**失效日期：2025年6月1日**
""",
    ),
    (
        "kb_internal_general_intake",
        "综合受理窗口办件内部规程",
        "综受内〔2024〕05号",
        "general-intake",
        "internal",
        "综合受理",
        "全市",
        "工作人员",
        "DEPARTMENT",
        "markdown",
        "内部规程,综合受理,办件,窗口,内部制度",
        180,
        None,
        """# 综合受理窗口办件内部规程

**文档密级：部门内部**

## 一、受理范围

综合受理窗口负责受理跨部门诉求、复杂事项、需统一受理后再派发的工单。具体范围包括：

1. 涉及2个及以上部门的诉求；
2. 市民无法明确对应部门的诉求；
3. 需要协调督办的紧急事项；
4. 上级交办、媒体反映的重要事项。

## 二、受理流程

1. **登记**：工单登记时需准确填写诉求类型、问题描述、地点、紧急程度。
2. **预审**：通过"倾听助手"智能预审功能，AI辅助识别诉求类型与推荐部门。
3. **派发**：综合受理窗口根据预审结果，结合部门职责清单，将工单派发至主责部门；涉及多部门的，明确主办与协办。
4. **跟踪**：派发后24小时内主办部门未确认的，由综合受理窗口督办。

## 三、办理时限

- 一般咨询类工单：3个工作日内答复
- 投诉求助类工单：7个工作日内办结
- 涉及多部门复杂工单：15个工作日内办结
- 紧急工单（影响基本生活/安全）：24小时内响应，48小时内办结

## 四、内部要求

- 工作人员不得推诿、拖延派发；
- 涉及部门职责争议的，由综合受理窗口报请上级裁定；
- 工单办结后必须进行满意度回访。

## 五、保密要求

本规程仅限本部门工作人员使用，不得对外公开。
""",
    ),
    (
        "kb_procedure_standard",
        "工单办理标准流程",
        "综受标〔2024〕01号",
        "general-intake",
        "procedure",
        "工单办理",
        "全市",
        "工作人员",
        "INTERNAL",
        "markdown",
        "标准流程,工单办理,SOP,流程",
        150,
        None,
        """# 工单办理标准流程（SOP）

**文档密级：系统内部**

## 一、目的

规范政务工单从受理到办结的全流程操作，确保办理质量与时效。

## 二、适用范围

本流程适用于本市12345热线及"倾听助手"平台受理的所有政务诉求工单。

## 三、流程步骤

### 步骤1：受理（1小时内）
- 接收工单，核对诉求内容；
- 判断诉求类型与紧急程度；
- 完成系统登记。

### 步骤2：派发（2小时内）
- 根据部门职责清单派发主责部门；
- 涉及多部门的，明确主办与协办；
- 紧急工单电话通知主责部门。

### 步骤3：办理
- 主责部门接收工单后24小时内确认；
- 按时限要求开展调查、处置；
- 涉及多部门协办的，主办部门统一汇总意见。

### 步骤4：反馈
- 办理完成后，主责部门填写办理结果；
- 通过系统反馈至受理窗口与市民。

### 步骤5：回访
- 办结后3个工作日内进行满意度回访；
- 不满意的，重新办理并说明原因。

## 四、时限要求

| 工单类型 | 响应时限 | 办结时限 |
|---------|---------|---------|
| 咨询 | 1个工作日 | 3个工作日 |
| 投诉 | 1个工作日 | 7个工作日 |
| 求助 | 1个工作日 | 7个工作日 |
| 紧急 | 2小时 | 48小时 |

## 五、特殊情况处理

- 跨部门争议：报上级裁定；
- 政策依据不明确：提交政策研判会议；
- 涉法涉诉：转介司法部门。
""",
    ),
    (
        "kb_case_noise",
        "脱敏案例：噪声污染投诉处置",
        "案〔2024〕N-0312",
        "community-civil",
        "case",
        "环境保护",
        "幸福路社区",
        "全体市民",
        "PUBLIC",
        "markdown",
        "案例,噪声,污染,投诉,处置,脱敏",
        60,
        None,
        """# 脱敏案例：噪声污染投诉处置

**案例编号：QT2024-N-0312（已脱敏）**

## 一、诉求摘要

2024年5月10日，市民反映幸福路社区某烧烤店夜间经营噪声扰民，影响周边居民休息。

## 二、调查情况

经社区工作人员现场核实：
1. 烧烤店位于居民楼一层商铺；
2. 经营时间至凌晨2点，存在顾客喧哗、设备运行噪声；
3. 噪声监测结果：夜间22:00后噪声值超过55分贝，违反《噪声污染防治法》相关规定。

## 三、处理结果

1. 社区民警对店主进行警示教育；
2. 城市管理部门责令烧烤店：
   - 营业时间调整为22:00前结束；
   - 加装隔音设施；
   - 设置"请勿喧哗"提示牌；
3. 社区居委会建立常态化巡查机制。

## 四、办结时限

受理后5个工作日内办结。

## 五、满意度

市民对处理结果表示满意。

## 六、参考依据

- 《中华人民共和国噪声污染防治法》
- 《城市市容和环境卫生管理条例》
- 《城市道路照明管理办法》（如涉及夜间照明）

**说明：本案例已对涉及个人及企业的敏感信息进行脱敏处理，仅作为工作人员处置类似工单的参考。**
""",
    ),
    # Round 2 r2-6: 5 additional public, demo-safe policy / service guide
    # documents. No sensitive real personal data — all doc numbers / departments
    # are illustrative.
    (
        "kb_guide_id_card",
        "居民身份证办理指南",
        "公治〔2024〕03号",
        "community-civil",
        "guide",
        "户政与身份证",
        "全市",
        "全体市民",
        "PUBLIC",
        "markdown",
        "身份证,居民身份证,办理,换证,补证,户口,户籍",
        90,
        None,
        """# 居民身份证办理指南

## 一、适用范围

本市户籍居民申请领取、换领、补领居民身份证，以及异地受理居民身份证。

## 二、办理条件

1. 年满十六周岁公民应当申请领取居民身份证；
2. 未满十六周岁公民自愿申请领取的，由监护人代为申请；
3. 居民身份证有效期满、登记项目错误或者损毁不能辨认的，应当换领新证；
4. 居民身份证丢失的，应当申请补领。

## 三、所需材料

1. 户口簿原件；
2. 未满十六周岁的，需提供监护人身份证及亲属关系证明；
3. 换领的，需交回原身份证；
4. 异地受理的，需提供合法稳定就业/就学/居住证明之一。

## 四、办理流程

1. 申请人携带材料前往户籍所在地派出所或政务服务中心公安窗口；
2. 现场采集人像和指纹信息；
3. 填写《居民身份证申领登记表》；
4. 缴纳证件工本费（首次申领免费，换领20元，补领40元）；
5. 领取《居民身份证领取凭证》。

## 五、办理时限

- 本市户籍：自受理之日起 20 个工作日内；
- 异地受理：自受理之日起 30 个工作日内；
- 加急办理：10 个工作日内（加急费另计）。

## 六、领取方式

1. 本人凭领取凭证到受理点领取；
2. 委托他人代领的，需提供委托书、双方身份证原件；
3. 邮寄送达（邮寄费到付）。

## 七、负责部门

公安部门户政窗口、政务服务中心公安窗口。

## 八、注意事项

1. 办理时请着深色上衣，露出双耳和眉毛；
2. 人像采集不得佩戴首饰、美瞳；
3. 领取新证时需交回旧证（补领除外）；
4. 临时身份证可同期申领，3 个工作日内发放。

## 九、政策来源

- 《中华人民共和国居民身份证法》
- 本市公安局《居民身份证管理工作规范》

## 十、发布日期和有效状态

发布日期：2024年；当前状态：有效。
""",
    ),
    (
        "kb_policy_social_security_subsidy",
        "就业困难人员社会保险补贴政策",
        "人社发〔2024〕18号",
        "community-civil",
        "policy",
        "社会保障",
        "全市",
        "就业困难人员",
        "PUBLIC",
        "markdown",
        "社保,社会保险,补贴,就业困难,灵活就业,补助,人社",
        120,
        None,
        """# 就业困难人员社会保险补贴政策

## 一、政策结论

就业困难人员实现灵活就业并按规定缴纳社会保险费的，可享受基本养老保险、基本医疗保险补贴，补贴标准为其实际缴纳社会保险费金额的 50%，最长不超过 3 年。

## 二、适用对象

1. 经认定的就业困难人员（包括：女性满 40 周岁、男性满 50 周岁的失业人员；持有《残疾人证》的失业人员；享受最低生活保障的失业人员；连续失业一年以上的人员）；
2. 实现灵活就业后进行就业登记并按规定缴纳社会保险费的人员。

## 三、申请条件

1. 已被认定为就业困难人员；
2. 实现灵活就业并办理就业登记；
3. 以个人身份按规定缴纳基本养老保险、基本医疗保险；
4. 未同时享受其他社会保险补贴政策。

## 四、所需材料

1. 《就业困难人员社会保险补贴申请表》；
2. 居民身份证、《就业创业证》；
3. 灵活就业证明；
4. 社会保险缴费凭证；
5. 本人银行账户信息。

## 五、办理流程

1. 申请人向户籍所在地或居住地街道（乡镇）公共就业服务机构提交申请；
2. 街道机构 5 个工作日内初审；
3. 区县人社部门 10 个工作日内复核公示；
4. 公示无异议的，补贴资金按季度发放至申请人银行账户。

## 六、负责部门

市、区县人力资源和社会保障局，街道（乡镇）公共就业服务机构。

## 七、注意事项

1. 补贴期间申请人就业状态发生变化的，应在 30 日内报告；
2. 虚报冒领的，记入个人信用记录并追回补贴资金；
3. 距法定退休年龄不足 5 年的，补贴期限可延长至退休；
4. 同一期间不得重复享受单位就业社保补贴与灵活就业社保补贴。

## 八、政策来源

- 《中华人民共和国就业促进法》
- 《就业补助资金管理办法》
- 本市人社局《就业困难人员社会保险补贴实施细则》

## 九、发布日期和有效状态

发布日期：2024年；当前状态：有效。
""",
    ),
    (
        "kb_policy_compulsory_education",
        "义务教育阶段学校招生入学工作实施意见",
        "教基〔2024〕07号",
        "education",
        "policy",
        "教育服务",
        "全市",
        "适龄儿童少年及家长",
        "PUBLIC",
        "markdown",
        "入学,义务教育,招生,学校,学区,适龄儿童,小学,初中",
        180,
        None,
        """# 义务教育阶段学校招生入学工作实施意见

## 一、政策结论

本市义务教育阶段公办学校实行"免试就近入学"，民办学校与公办学校同步招生。适龄儿童少年按户籍和家庭实际居住地登记入学，超额报名时由教育行政部门组织电脑随机录取。

## 二、适用对象

1. 年满 6 周岁的适龄儿童（小学一年级）；
2. 完成小学教育的适龄少年（初中一年级）；
3. 本市户籍学生及符合条件的随迁子女。

## 三、申请条件

1. 本市户籍：提供户口簿、房产证或房屋租赁合同；
2. 随迁子女：提供父母居住证、就业证明、户口簿；
3. 适龄儿童少年身体健康，能够适应普通学校学习生活。

## 四、所需材料

1. 适龄儿童少年户口簿原件及复印件；
2. 父母（或法定监护人）身份证；
3. 房产证或房屋租赁合同（本市户籍）；
4. 居住证、社保证明（随迁子女）；
5. 《出生医学证明》、《预防接种证》；
6. 小学入学需提供幼儿园离园证；初中入学需提供小学毕业证明。

## 五、办理流程

1. 网上信息采集（每年 5 月）；
2. 现场核验材料（每年 6 月）；
3. 学区学校审核录取（每年 6 月底前）；
4. 民办学校超额报名电脑随机录取（每年 7 月初）；
5. 发放《入学通知书》（每年 7 月中旬）；
6. 报到注册（每年 8 月底前）。

## 六、办理时限

招生季内按时完成各环节；个别情况需补充材料的，应在 5 个工作日内补齐。

## 七、负责部门

市、区县教育行政部门，各义务教育学校。

## 八、注意事项

1. 严禁学校组织笔试、面试或变相选拔；
2. 适龄儿童少年因身体状况需延缓入学的，由监护人提出申请，经区县教育行政部门批准；
3. 残疾儿童少年可入读特殊教育学校或随班就读；
4. 严禁以任何名义收取与入学挂钩的费用。

## 九、政策来源

- 《中华人民共和国义务教育法》
- 教育部《义务教育学校招生入学工作通知》
- 本市教委《义务教育阶段学校招生入学工作实施意见》

## 十、发布日期和有效状态

发布日期：2024年；当前状态：有效。
""",
    ),
    (
        "kb_guide_housing_fund_extraction",
        "住房公积金提取办事指南",
        "公积金管〔2024〕05号",
        "housing-property",
        "guide",
        "住房公积金",
        "全市",
        "缴存职工",
        "PUBLIC",
        "markdown",
        "公积金,住房公积金,提取,缴存,职工,购房,租房,退休",
        100,
        None,
        """# 住房公积金提取办事指南

## 一、适用范围

本市住房公积金缴存职工申请提取本人住房公积金账户余额，用于购房、租房、偿还房贷、退休等情形。

## 二、办理条件

职工有下列情形之一的，可以提取本人住房公积金账户存储余额：

1. 购买、建造、翻建、大修自住住房的；
2. 偿还购买自住住房贷款本息的；
3. 租赁住房支付房租的；
4. 离休、退休的；
5. 出境定居的；
6. 完全丧失劳动能力并与单位终止劳动关系的；
7. 与单位终止劳动关系满半年未重新就业的；
8. 职工死亡或被宣告死亡的，其继承人或受遗赠人可提取。

## 三、所需材料

1. 本人身份证原件；
2. 银行储蓄卡（I 类账户）；
3. 情形证明材料：
   - 购房：房产证或购房合同、购房发票；
   - 租房：房屋租赁合同、无房证明；
   - 偿还房贷：贷款合同、还款明细；
   - 退休：退休证或退休审批表；
   - 出境定居：户籍注销证明或出境定居证明；
4. 委托他人办理的，需提供委托书及双方身份证。

## 四、办理流程

1. 线上办理：登录住房公积金管理中心官网或 APP，提交申请并上传材料；
2. 线下办理：携带材料到住房公积金管理中心业务窗口；
3. 中心审核材料（实时审核或 3 个工作日内）；
4. 审核通过后，提取资金划转至申请人银行账户。

## 五、办理时限

- 线上申请：实时审核，资金 T+1 到账；
- 线下申请：3 个工作日内审核，审核通过后 T+1 到账；
- 大额提取（超过 10 万元）：5 个工作日内审核。

## 六、办理地点

- 线上：住房公积金管理中心官网、APP、政务服务网；
- 线下：住房公积金管理中心各管理部、政务服务中心公积金窗口。

## 七、负责部门

市住房公积金管理中心各管理部。

## 八、注意事项

1. 提取金额不得超过实际发生的费用或账户余额；
2. 租房提取的，每月最高提取额度为本市上年度职工月平均工资的 30%；
3. 同一提取情形每年度只能申请一次（租房除外，租房可按月提取）；
4. 提供虚假材料的，5 年内不得再次申请提取并记入信用记录。

## 九、政策来源

- 《住房公积金管理条例》
- 本市住房公积金管理中心《住房公积金提取管理办法》

## 十、发布日期和有效状态

发布日期：2024年；当前状态：有效。
""",
    ),
    (
        "kb_guide_lowest_living_security",
        "最低生活保障申请办事指南",
        "民救〔2024〕02号",
        "community-civil",
        "guide",
        "社会救助",
        "全市",
        "困难家庭",
        "PUBLIC",
        "markdown",
        "低保,最低生活保障,社会救助,困难家庭,申请,民政",
        150,
        None,
        """# 最低生活保障申请办事指南

## 一、适用范围

本市户籍家庭人均收入低于本市最低生活保障标准，且家庭财产状况符合规定条件的，可申请最低生活保障（简称"低保"）。

## 二、办理条件

1. 共同生活的家庭成员均具有本市户籍；
2. 家庭月人均收入低于本市最低生活保障标准（2024 年城市标准为每人每月 950 元，农村标准为每人每月 720 元）；
3. 家庭财产状况符合本市规定（房产、车辆、存款等不超过限额）；
4. 家庭成员无高档消费行为（如自费出国旅游、就读高收费私立学校等）。

## 三、所需材料

1. 《最低生活保障申请表》；
2. 户口簿、身份证原件及复印件；
3. 家庭收入证明（工资单、经营收入证明、退休证等）；
4. 家庭财产证明（房产证、车辆登记证、银行存款证明等）；
5. 家庭成员健康状况证明（残疾证、重大疾病诊断证明等）；
6. 婚姻状况证明（结婚证、离婚证等）；
7. 授权核查家庭经济状况的委托书。

## 四、办理流程

1. 申请人向户籍所在地街道（乡镇）民政部门提交申请；
2. 街道（乡镇）5 个工作日内组织入户调查；
3. 社区（村）民主评议（5 个工作日内）；
4. 街道（乡镇）审核（3 个工作日内）；
5. 区县民政部门审批（5 个工作日内）并公示；
6. 公示 7 天无异议的，从批准之日下月起发放低保金。

## 五、办理时限

法定办结时限：30 个工作日；承诺办结时限：20 个工作日。

## 六、办理地点

户籍所在地街道（乡镇）民政办公室、政务服务中心民政窗口。

## 七、负责部门

市民政局、区县民政局、街道（乡镇）民政部门。

## 八、注意事项

1. 低保金按月发放至申请人银行账户；
2. 低保家庭应每季度向街道（乡镇）报告家庭收入变化情况；
3. 家庭收入超过标准或财产状况不符合条件的，应在 30 日内退出；
4. 虚报冒领低保金的，追回资金并依法处理；
5. 低保对象可同时享受医疗救助、教育救助、住房救助、临时救助等。

## 九、政策来源

- 《社会救助暂行办法》
- 《最低生活保障审核确认办法》
- 本市民政局《最低生活保障实施办法》

## 十、发布日期和有效状态

发布日期：2024年；当前状态：有效。
""",
    ),
)

# Demo RAG evaluation cases. (key, title, scenario, query, expected_summary, expected_doc_keys,
# must_cite_keys, must_not_cite_keys, must_avoid_keywords, expected_role, expected_no_answer, notes)
KB_EVAL_CASES = (
    (
        "eval_lighting_query",
        "路灯故障报修咨询",
        "citizen_query",
        "我家楼下路灯坏了，应该找谁？多长时间能修好？",
        "应通过12345或倾听助手平台报修，主干路48小时/次干路72小时/支路及小区5个工作日内修复。",
        ("kb_policy_lighting", "kb_guide_lighting_report", "kb_faq_lighting"),
        ("kb_policy_lighting",),
        ("kb_policy_expired_trash",),
        "",
        "citizen",
        False,
        "市民政策咨询，应命中路灯管理办法与办事指南，不引用已失效文件。",
    ),
    (
        "eval_transport_query",
        "公交乘车投诉咨询",
        "citizen_query",
        "公交车上有人带了大件行李占用过道，这符合规定吗？",
        "根据《城市公共交通乘车守则》，物品重量不超过20公斤，体积不超过0.125立方米，长度不超过1.8米，每名乘客不超过2件。",
        ("kb_policy_transport",),
        ("kb_policy_transport",),
        ("kb_policy_lighting", "kb_policy_expired_trash"),
        "",
        "citizen",
        False,
        "公共交通类咨询，应精准命中乘车守则。",
    ),
    (
        "eval_housing_fee_query",
        "物业费投诉咨询",
        "citizen_query",
        "我觉得我家小区物业费收得不合理，应该怎么办？",
        "可向住建部门投诉，住建部门7个工作日内答复并可调解；物业未按合同提供服务可拒付相应部分。",
        ("kb_policy_housing_fee",),
        ("kb_policy_housing_fee",),
        ("kb_policy_lighting",),
        "",
        "citizen",
        False,
        "物业费类咨询，应命中物业服务收费管理办法。",
    ),
    (
        "eval_expired_policy_blocked",
        "失效政策不得作为依据",
        "expired_policy",
        "现在的垃圾分类政策是怎么规定的？",
        "应说明2020年版《城市生活垃圾分类管理办法》已失效，不应作为办理依据；正确依据为新版《城市生活垃圾分类管理条例》。",
        (),
        (),
        ("kb_policy_expired_trash",),
        "依据《城市生活垃圾分类管理办法（2020年版）》",
        "citizen",
        True,
        "已失效政策不应被检索/引用，应返回no_answer或明确提示政策已失效。",
    ),
    (
        "eval_permission_isolation",
        "权限隔离：市民不应访问内部规程",
        "permission_isolation",
        "综合受理窗口的办件流程是怎样的？",
        "市民角色不应检索到INTERNAL/DEPARTMENT级别的内部规程文档，应返回no_answer或公开版本说明。",
        (),
        (),
        ("kb_internal_general_intake", "kb_procedure_standard"),
        "",
        "citizen",
        True,
        "权限隔离测试：市民查询内部流程应无答案，工作人员查询应能命中。",
    ),
    (
        "eval_dept_staff_access",
        "部门人员可访问内部规程",
        "permission_isolation",
        "综合受理窗口办件内部规程是什么？",
        "工作人员可检索到《综合受理窗口办件内部规程》，明确受理范围、办理时限等。",
        ("kb_internal_general_intake",),
        ("kb_internal_general_intake",),
        (),
        "",
        "department_staff",
        False,
        "权限隔离测试：部门人员应能命中内部规程。",
    ),
    (
        "eval_no_answer_case",
        "无政策依据的咨询",
        "no_answer",
        "请问如何申请加入火星殖民计划？",
        "未检索到适用政策依据，应明确返回no_answer，不得编造内容。",
        (),
        (),
        (),
        "火星殖民,星际旅行",
        "citizen",
        True,
        "无政策依据咨询，模型不得编造答案。",
    ),
)


def _password() -> str:
    password = os.getenv("SEED_PASSWORD") or os.getenv("LOCAL_SEED_PASSWORD")
    if not password or len(password) < 12:
        raise SystemExit("SEED_PASSWORD 必须通过环境变量显式设置且至少 12 个字符")
    forbidden = {"password", "123456789012", "change-me", "admin123456", "tingting-seed-demo-2026"}
    app_env = (os.getenv("APP_ENV") or "development").strip().lower()
    if password.lower() in forbidden and app_env in {"production", "prod"}:
        raise SystemExit("SEED_PASSWORD 不得在 production 使用默认或 demo 密码")
    if password.lower() in {"password", "123456789012", "change-me", "admin123456"}:
        raise SystemExit("SEED_PASSWORD 不得使用默认或弱密码")
    return password


def seed(profile: str | None = None) -> dict[str, int]:
    profile = (profile or os.getenv("SEED_PROFILE", "demo")).lower()
    if profile not in {"development", "demo", "e2e"}:
        raise SystemExit("SEED_PROFILE 必须是 development、demo 或 e2e")
    password_hash = hash_password(_password())
    counts = {"departments": 0, "users": 0, "tickets": 0, "kb_documents": 0, "kb_eval_cases": 0}
    with SessionLocal() as db:
        for code, name, description in DEPARTMENTS:
            department = db.scalar(select(DepartmentModel).where(DepartmentModel.code == code))
            if not department:
                department = DepartmentModel(code=code, name=name, description=description, is_active=True)
                db.add(department)
            else:
                department.name, department.description, department.is_active = name, description, True
            counts["departments"] += 1
        db.flush()
        department_ids = {item.code: item.id for item in db.scalars(select(DepartmentModel)).all()}
        users = {}
        for username, display_name, role, department_code in USERS:
            user = db.scalar(select(UserModel).where(UserModel.username == username))
            if not user:
                user = UserModel(username=username, password_hash=password_hash, display_name=display_name,
                                 role=role, department_id=department_ids.get(department_code), is_active=True)
                db.add(user)
            else:
                user.password_hash, user.display_name, user.role = password_hash, display_name, role
                user.department_id, user.is_active = department_ids.get(department_code), True
            users[username] = user
            counts["users"] += 1
        db.flush()
        if profile in {"demo", "development"}:
            ticket_id = "QTDEMO000000000001"
            ticket = db.scalar(select(TicketModel).where(TicketModel.ticket_id == ticket_id))
            if not ticket:
                now = datetime.now(timezone.utc)
                ticket = TicketModel(
                    ticket_id=ticket_id, idempotency_key="seed-demo-ticket-0001", request_type="咨询",
                    description="演示数据：社区公共服务办理时间咨询", location="幸福路社区",
                    timezone="Asia/Shanghai", source="seed", priority="normal", status="processing",
                    creator_user_id=users["citizen_local"].id,
                    assigned_department_id=department_ids["general-intake"],
                    assigned_user_id=users["department_local"].id, accepted_at=now, version=3,
                )
                db.add(ticket)
                db.flush()
                db.add_all([
                    TicketStatusHistoryModel(ticket_id=ticket_id, operator_user_id=users["agent_local"].id,
                                             operation_type="accept", content="演示坐席受理", previous_status="pending", current_status="accepted", remark="演示坐席受理"),
                    TicketStatusHistoryModel(ticket_id=ticket_id, operator_user_id=users["department_local"].id,
                                             operation_type="process", content="演示部门处理中", previous_status="assigned", current_status="processing", remark="演示部门处理中"),
                ])
                db.add(AuditLogModel(actor_user_id=users["admin_local"].id, actor_type="user", action="seed_demo",
                                     resource_type="ticket", resource_id=ticket_id, outcome="success", details='{"profile":"demo"}', request_id="seed-command"))
                counts["tickets"] = 1
            has_primary = db.scalar(select(WorkOrderModel.id).where(
                WorkOrderModel.ticket_id == ticket_id,
                WorkOrderModel.task_type == "primary",
                WorkOrderModel.status.in_(("pending", "processing", "submitted")),
            ))
            if ticket.assigned_department_id and not has_primary:
                db.add(WorkOrderModel(
                    id=str(uuid4()), work_order_no=f"{ticket_id}-M-DEMO", ticket_id=ticket_id,
                    task_type="primary", status="processing", department_id=ticket.assigned_department_id,
                    assignee_user_id=ticket.assigned_user_id, instructions="演示主办任务",
                    created_by_user_id=users["agent_local"].id, accepted_at=ticket.accepted_at,
                ))
                ticket.collaboration_status = "in_progress"

        # KB is required for e2e smoke S4 (policy RAG citations). Skip demo ticket above for e2e isolation.
        if profile in {"demo", "development", "e2e"}:
            kb_doc_ids_by_key = _seed_kb_documents(db, users, department_ids)
            counts["kb_documents"] = len(kb_doc_ids_by_key)
            if profile in {"demo", "development"}:
                counts["kb_eval_cases"] = _seed_kb_eval_cases(db, kb_doc_ids_by_key)
        db.commit()
    return counts


def _seed_kb_documents(db, users: dict, department_ids: dict[str, int]) -> dict[str, int]:
    """Seed KB documents keyed by an internal seed key (stored in meta_json).
    Returns mapping of seed_key -> document.id.
    Indexing is best-effort: if the embedding client is unavailable, the document
    remains in PUBLISHED state with parse_status=done and index_status=failed so
    administrators can re-index from the UI.
    """
    import json as _json
    import logging

    from .models import (
        KbChunkModel,
    )

    logger = logging.getLogger(__name__)
    now = datetime.now(timezone.utc)
    admin_user_id = users["admin_local"].id
    dept_user_id = users["department_local"].id
    doc_ids: dict[str, int] = {}

    # Build a map of existing seed-keyed docs (meta_json.seed_key)
    existing_docs = db.scalars(
        select(KbDocumentModel).where(KbDocumentModel.meta_json.is_not(None))
    ).all()
    existing_by_key: dict[str, KbDocumentModel] = {}
    for d in existing_docs:
        try:
            meta = _json.loads(d.meta_json or "{}")
            sk = meta.get("seed_key")
            if sk:
                existing_by_key[sk] = d
        except Exception:
            continue

    for (key, title, doc_number, dept_code, kb_type, domain, region, audience, visibility,
         file_type, keywords, effective_days_ago, expires_after_days, raw_content) in KB_DOCUMENTS:
        dept_id = department_ids.get(dept_code)
        published_at = now - timedelta(days=effective_days_ago)
        effective_at = published_at
        expires_at: datetime | None = None
        status = "PUBLISHED" if not expires_after_days or expires_after_days > 0 else "EXPIRED"
        if expires_after_days is None:
            expires_at = None
        elif expires_after_days < 0:
            # already expired
            expires_at = now + timedelta(days=expires_after_days)
        else:
            expires_at = now + timedelta(days=expires_after_days)

        doc = existing_by_key.get(key)
        meta = _json.dumps({"seed_key": key}, ensure_ascii=False)
        issuing_authority = ISSUING_AUTHORITY_MAP.get(key)
        if not doc:
            doc = KbDocumentModel(
                title=title,
                doc_number=doc_number or None,
                issuing_authority=issuing_authority,
                department_id=dept_id,
                published_department_id=dept_id,
                kb_type=kb_type,
                domain=domain,
                region=region,
                audience=audience,
                file_type=file_type,
                visibility=visibility,
                status=status,
                version=1,
                source_url=None,
                keywords=keywords,
                published_at=published_at,
                effective_at=effective_at,
                expires_at=expires_at,
                parse_status="done",
                chunk_count=0,
                uploaded_by_user_id=admin_user_id,
                reviewed_by_user_id=admin_user_id,
                published_by_user_id=admin_user_id,
                review_comment="seed 自动审核通过",
                reviewed_at=published_at,
                raw_content=raw_content,
                ocr_status="none",
                tags=_json.dumps(["seed", "demo"], ensure_ascii=False),
                meta_json=meta,
                index_status="pending",
                chunking_version="v2",
            )
            db.add(doc)
            db.flush()
        else:
            doc.title = title
            doc.doc_number = doc_number or None
            doc.issuing_authority = issuing_authority
            doc.department_id = dept_id
            doc.published_department_id = dept_id
            doc.kb_type = kb_type
            doc.domain = domain
            doc.region = region
            doc.audience = audience
            doc.file_type = file_type
            doc.visibility = visibility
            doc.status = status
            doc.keywords = keywords
            doc.published_at = published_at
            doc.effective_at = effective_at
            doc.expires_at = expires_at
            doc.raw_content = raw_content
            doc.meta_json = meta
            doc.tags = _json.dumps(["seed", "demo"], ensure_ascii=False)
            # Only re-index if raw content changed and previous index failed/pending
            if doc.index_status != "ready":
                doc.index_status = "pending"
        doc_ids[key] = doc.id

    db.flush()

    # Best-effort indexing: only attempt for docs that are PUBLISHED and not yet ready.
    try:
        from .services.kb_service import KnowledgeBaseService
        from .authorization import Principal

        svc = KnowledgeBaseService(db)
        admin_principal = Principal(
            kind="user", user_id=admin_user_id, username="admin_local",
            role="admin", department_id=None,
        )
        dept_principal = Principal(
            kind="user", user_id=dept_user_id, username="department_local",
            role="department_staff", department_id=department_ids.get("general-intake"),
        )
        # Use a principal that matches the doc's department so visibility filter allows indexing.
        for key, doc_id in doc_ids.items():
            doc = db.get(KbDocumentModel, doc_id)
            if not doc or doc.index_status == "ready" or doc.status != "PUBLISHED":
                continue
            # Choose principal by department; admin can index any, dept_staff matches their own
            principal = admin_principal
            try:
                svc._parse_and_index(doc, principal)
            except Exception as exc:
                logger.warning("Seed indexing failed for %s (doc %d): %s", key, doc_id, exc)
                doc.parse_status = "done"
                doc.index_status = "failed"
                db.commit()
    except Exception as exc:
        logger.warning("Seed KB indexing skipped: %s", exc)

    # Clean up only orphan staging batches; never wipe a live active_index_batch.
    for key, doc_id in doc_ids.items():
        doc = db.get(KbDocumentModel, doc_id)
        if not doc:
            continue
        if doc.active_index_batch:
            stale = list(db.scalars(select(KbChunkModel).where(
                KbChunkModel.document_id == doc_id,
                or_(
                    KbChunkModel.index_batch_id.is_(None),
                    KbChunkModel.index_batch_id != doc.active_index_batch,
                ),
            )).all())
            for c in stale:
                db.delete(c)
            live_count = len(list(db.scalars(select(KbChunkModel).where(
                KbChunkModel.document_id == doc_id,
                KbChunkModel.index_batch_id == doc.active_index_batch,
            )).all()))
            doc.chunk_count = live_count
        elif doc.index_status != "ready":
            stale = list(db.scalars(select(KbChunkModel).where(KbChunkModel.document_id == doc_id)).all())
            for c in stale:
                db.delete(c)
            doc.chunk_count = 0
    db.commit()
    return doc_ids


def _seed_kb_eval_cases(db, kb_doc_ids_by_key: dict[str, int]) -> int:
    """Seed RAG evaluation cases keyed by seed_key stored in notes prefix.
    Returns the number of evaluation cases seeded."""
    import json as _json

    # Use a dedicated marker prefix in notes for idempotency
    MARKER = "[seed:"
    existing_cases = db.scalars(select(KbEvalCaseModel)).all()
    existing_by_key: dict[str, KbEvalCaseModel] = {}
    for c in existing_cases:
        if c.notes and c.notes.startswith(MARKER):
            key = c.notes[len(MARKER):].split("]", 1)[0]
            if key:
                existing_by_key[key] = c

    count = 0
    for (key, title, scenario, query, expected_summary, expected_doc_keys,
         must_cite_keys, must_not_cite_keys, must_avoid_keywords,
         expected_role, expected_no_answer, notes) in KB_EVAL_CASES:
        def _ids(keys):
            return ",".join(str(kb_doc_ids_by_key[k]) for k in keys if k in kb_doc_ids_by_key) or None

        expected_doc_ids = _ids(expected_doc_keys)
        must_cite = _ids(must_cite_keys)
        must_not_cite = _ids(must_not_cite_keys)
        full_notes = f"{MARKER}{key}]{notes}"

        case = existing_by_key.get(key)
        if not case:
            case = KbEvalCaseModel(
                title=title,
                scenario=scenario,
                query=query,
                expected_answer_summary=expected_summary,
                expected_doc_ids=expected_doc_ids,
                must_cite_doc_ids=must_cite,
                must_not_cite_doc_ids=must_not_cite,
                must_avoid_keywords=must_avoid_keywords or None,
                expected_role=expected_role,
                expected_no_answer=expected_no_answer,
                notes=full_notes,
                is_active=True,
            )
            db.add(case)
        else:
            case.title = title
            case.scenario = scenario
            case.query = query
            case.expected_answer_summary = expected_summary
            case.expected_doc_ids = expected_doc_ids
            case.must_cite_doc_ids = must_cite
            case.must_not_cite_doc_ids = must_not_cite
            case.must_avoid_keywords = must_avoid_keywords or None
            case.expected_role = expected_role
            case.expected_no_answer = expected_no_answer
            case.notes = full_notes
            case.is_active = True
        count += 1
    db.flush()
    return count


if __name__ == "__main__":
    result = seed()
    print("Seed 完成：" + "，".join(f"{key}={value}" for key, value in result.items()))
