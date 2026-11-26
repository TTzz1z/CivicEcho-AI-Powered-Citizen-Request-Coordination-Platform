"""Idempotent development/demo/E2E seed. The password must come from the environment."""
import hashlib
import io
import json
import logging
import os
import struct
import uuid
import zlib
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from . import storage as storage_module
from .ai_schemas import validate_handling_response, validate_triage_response
from .config import get_settings
from .database import SessionLocal
from .models import (
    AiSuggestionModel,
    AppealModel,
    AuditLogModel,
    CategoryModel,
    DepartmentModel,
    FollowUpTaskModel,
    KbDocumentModel,
    KbEvalCaseModel,
    NotificationModel,
    PhoneFollowUpRecordModel,
    TicketAttachmentModel,
    TicketFeedbackModel,
    TicketModel,
    TicketStatusHistoryModel,
    UserModel,
    WorkOrderHistoryModel,
    WorkOrderModel,
)
from .security import hash_password

logger = logging.getLogger(__name__)
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


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
    forbidden = {"password", "123456789012", "change-me", "admin123456"}
    app_env = (os.getenv("APP_ENV") or "development").strip().lower()
    is_legacy_demo = password.lower().startswith("tingting-seed-demo-")
    if (password.lower() in forbidden or is_legacy_demo) and app_env in {"production", "prod"}:
        raise SystemExit("SEED_PASSWORD 不得在 production 使用默认或 demo 密码")
    if password.lower() in {"password", "123456789012", "change-me", "admin123456"}:
        raise SystemExit("SEED_PASSWORD 不得使用默认或弱密码")
    return password


def seed(profile: str | None = None) -> dict[str, int]:
    if (os.getenv("APP_ENV") or get_settings().app_env).strip().lower() in {"production", "prod"}:
        raise SystemExit("生产环境禁止加载演示数据。请使用 python -m app.bootstrap_admin。")
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
            lifecycle_counts = _seed_demo_lifecycle(db, users, department_ids)
            counts.update(lifecycle_counts)

        # KB is required for e2e smoke S4 (policy RAG citations). Skip demo ticket above for e2e isolation.
        if profile in {"demo", "development", "e2e"}:
            kb_doc_ids_by_key = _seed_kb_documents(db, users, department_ids)
            counts["kb_documents"] = len(kb_doc_ids_by_key)
            if profile in {"demo", "development"}:
                counts["kb_eval_cases"] = _seed_kb_eval_cases(db, kb_doc_ids_by_key)
        db.commit()
    return counts


def _deterministic_uuid4(seed_key: str) -> str:
    """Return a deterministic lowercase UUID4-format string matching worker ATTACHMENT_KEY."""
    raw = bytearray(hashlib.sha256(f"civicecho-seed:{seed_key}".encode("utf-8")).digest()[:16])
    raw[6] = (raw[6] & 0x0F) | 0x40
    raw[8] = (raw[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(raw)))


def _shanghai_day_anchor(now: datetime, days_ago: int, hour: int = 10, minute: int = 15) -> datetime:
    """Return a UTC timestamp anchored to a specific Asia/Shanghai day offset in [0..13]."""
    sh_now = now.astimezone(SHANGHAI_TZ)
    day_start = sh_now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_ago)
    if days_ago == 0:
        candidate = now - timedelta(minutes=25 + minute)
        if candidate < day_start:
            candidate = day_start + timedelta(minutes=10)
        return candidate.astimezone(timezone.utc)
    return day_start.replace(hour=hour, minute=minute).astimezone(timezone.utc)


def _build_demo_pdf_bytes(heading: str, body_lines: list[str]) -> bytes:
    """Build a valid single-page PDF 1.4 parseable by pypdf and pdfjs-dist."""
    def _esc(text: str) -> str:
        return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    stream_cmds = [
        "0.11 0.27 0.53 rg",
        "48 770 499 42 re f",
        "1 1 1 rg",
        f"BT /F1 15 Tf 62 786 Td ({_esc(heading)}) Tj ET",
        "0.15 0.18 0.22 rg",
        "48 748 499 1 re f",
    ]
    y = 720
    for idx, line in enumerate(body_lines):
        size = 11 if idx == 0 else 10
        stream_cmds.append(f"BT /F1 {size} Tf 56 {y} Td ({_esc(line)}) Tj ET")
        y -= 20
    stream_bytes = ("\n".join(stream_cmds) + "\n").encode("latin-1")

    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream_bytes)).encode("ascii") + b" >>\nstream\n" + stream_bytes + b"endstream",
    ]

    chunks: list[bytes] = [b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"]
    offsets: list[int] = [0]
    for obj_num, body in enumerate(objects, start=1):
        offsets.append(sum(len(c) for c in chunks))
        chunks.append(f"{obj_num} 0 obj\n".encode("ascii") + body + b"\nendobj\n")

    xref_offset = sum(len(c) for c in chunks)
    xref_lines = [f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii")]
    for off in offsets[1:]:
        xref_lines.append(f"{off:010d} 00000 n \n".encode("ascii"))
    trailer = (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    ).encode("ascii")
    return b"".join(chunks + xref_lines + [trailer])


def _build_demo_png_bytes(width: int = 160, height: int = 120) -> bytes:
    """Build a valid RGB PNG image using stdlib zlib + CRC32."""
    def _chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack("!I", len(data)) + tag + data + struct.pack("!I", crc)

    ihdr = struct.pack("!IIBBBBB", width, height, 8, 2, 0, 0, 0)
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for x in range(width):
            if y < 24:
                rows.extend((28, 72, 138))
            elif 34 <= y < 96 and 20 <= x < 140:
                if 50 <= y < 78 and 68 <= x < 92:
                    rows.extend((232, 148, 38))
                else:
                    rows.extend((216, 224, 234))
            else:
                rows.extend((244, 246, 249))
    idat = zlib.compress(bytes(rows), level=6)
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")


def _seed_demo_lifecycle(
    db,
    users: dict[str, UserModel],
    department_ids: dict[str, int],
) -> dict[str, int]:
    """Seed 18 realistic municipal tickets across 14 days and full sub-modules (demo/dev only)."""
    now = datetime.now(timezone.utc)
    categories_by_code = {
        cat.code: cat.id for cat in db.scalars(select(CategoryModel)).all()
    }
    tickets_by_id = _seed_demo_tickets(db, users, department_ids, categories_by_code, now)
    attachments_count = _seed_demo_attachments(db, users, department_ids, tickets_by_id, now)
    ai_count = _seed_demo_ai_suggestions(db, users, department_ids, tickets_by_id, now)
    aftercare_counts = _seed_demo_aftercare(db, users, tickets_by_id, now)
    notifications_count = _seed_demo_notifications(db, users, tickets_by_id, now)
    _seed_demo_audit_logs(db, users, tickets_by_id, now)
    return {
        "tickets": len(tickets_by_id),
        "attachments": attachments_count,
        "ai_suggestions": ai_count,
        "notifications": notifications_count,
        "follow_up_tasks": aftercare_counts["follow_up_tasks"],
        "appeals": aftercare_counts["appeals"],
    }


def _seed_demo_tickets(
    db,
    users: dict[str, UserModel],
    department_ids: dict[str, int],
    categories_by_code: dict[str, int],
    now: datetime,
) -> dict[str, TicketModel]:
    citizen_id = users["citizen_local"].id
    agent_id = users["agent_local"].id
    dept_user_id = users["department_local"].id
    admin_id = users["admin_local"].id

    def _dept(code: str | None) -> int | None:
        return department_ids.get(code) if code else None

    def _cat(code: str | None) -> int | None:
        return categories_by_code.get(code) if code else None

    t1_created = _shanghai_day_anchor(now, 1, hour=9, minute=30)
    t1_accepted = t1_created + timedelta(minutes=35)
    t2_created = _shanghai_day_anchor(now, 0, hour=10, minute=10)
    t3_created = _shanghai_day_anchor(now, 0, hour=8, minute=20)
    t4_created = _shanghai_day_anchor(now, 1, hour=14, minute=15)
    t4_accepted = t4_created + timedelta(minutes=40)
    t5_created = _shanghai_day_anchor(now, 2, hour=9, minute=45)
    t5_accepted = t5_created + timedelta(minutes=30)
    t6_created = _shanghai_day_anchor(now, 2, hour=15, minute=10)
    t6_accepted = t6_created + timedelta(minutes=25)
    t7_created = _shanghai_day_anchor(now, 3, hour=11, minute=5)
    t7_accepted = t7_created + timedelta(minutes=50)
    t8_created = _shanghai_day_anchor(now, 4, hour=10, minute=20)
    t8_accepted = t8_created + timedelta(minutes=35)
    t9_created = _shanghai_day_anchor(now, 5, hour=14, minute=40)
    t9_accepted = t9_created + timedelta(minutes=45)
    t10_created = _shanghai_day_anchor(now, 6, hour=9, minute=15)
    t10_accepted = t10_created + timedelta(minutes=30)
    t11_created = _shanghai_day_anchor(now, 7, hour=11, minute=30)
    t11_accepted = t11_created + timedelta(minutes=40)
    t12_created = _shanghai_day_anchor(now, 8, hour=13, minute=25)
    t12_accepted = t12_created + timedelta(minutes=55)
    t13_created = _shanghai_day_anchor(now, 9, hour=10, minute=5)
    t13_accepted = t13_created + timedelta(minutes=35)
    t13_resolved = t13_created + timedelta(hours=18)
    t14_created = _shanghai_day_anchor(now, 10, hour=15, minute=20)
    t14_accepted = t14_created + timedelta(minutes=45)
    t14_resolved = t14_created + timedelta(hours=30)
    t15_created = _shanghai_day_anchor(now, 11, hour=9, minute=50)
    t15_accepted = t15_created + timedelta(minutes=25)
    t15_resolved = t15_created + timedelta(hours=14)
    t15_closed = t15_resolved + timedelta(hours=6)
    t16_created = _shanghai_day_anchor(now, 12, hour=11, minute=10)
    t16_accepted = t16_created + timedelta(minutes=40)
    t16_resolved = t16_created + timedelta(hours=22)
    t16_closed = t16_resolved + timedelta(hours=14)
    t17_created = _shanghai_day_anchor(now, 13, hour=10, minute=30)
    t17_accepted = t17_created + timedelta(minutes=50)
    t17_resolved = t17_created + timedelta(hours=40)
    t17_closed = t17_resolved + timedelta(hours=8)
    t18_created = _shanghai_day_anchor(now, 13, hour=16, minute=15)

    ticket_specs = [
        {
            "ticket_id": "QTDEMO000000000001",
            "idempotency_key": "seed-demo-ticket-0001",
            "request_type": "咨询",
            "description": "演示数据：社区公共服务办理时间咨询",
            "location": "幸福路社区",
            "event": "公共服务大厅便民窗口咨询",
            "occurred_at_text": "工作日 09:00-17:00",
            "target": "社区便民服务中心",
            "contact": "13800138001",
            "source": "seed",
            "priority": "normal",
            "status": "processing",
            "creator_user_id": citizen_id,
            "assigned_department_id": _dept("general-intake"),
            "assigned_user_id": dept_user_id,
            "category_id": _cat("CSGL-GGSS-GD"),
            "collaboration_status": "in_progress",
            "created_at": t1_created,
            "accepted_at": t1_accepted,
            "accept_due_at": t1_created + timedelta(hours=2),
            "resolve_due_at": now + timedelta(hours=48),
            "version": 3,
            "history": [
                ("accept", "pending", "accepted", agent_id, "演示坐席受理", "public", t1_accepted),
                ("process", "assigned", "processing", dept_user_id, "演示部门处理中", "public", t1_accepted + timedelta(minutes=20)),
            ],
            "work_orders": [
                {
                    "work_order_no": "QTDEMO000000000001-M-DEMO",
                    "task_type": "primary",
                    "status": "processing",
                    "department_id": _dept("general-intake"),
                    "assignee_user_id": dept_user_id,
                    "instructions": "演示主办任务",
                    "accepted_at": t1_accepted,
                    "history": [
                        ("create", None, "pending", agent_id, "派发综合受理主办工单", t1_accepted),
                        ("start", "pending", "processing", dept_user_id, "部门人员开始办理", t1_accepted + timedelta(minutes=20)),
                    ],
                },
            ],
        },
        {
            "ticket_id": "QT2026110000000002",
            "idempotency_key": "seed-demo-ticket-0002",
            "request_type": "投诉",
            "description": "建设北路与新华街交叉口东侧连续三盏路灯夜间不亮，行人过街视线受阻。",
            "location": "建设北路与新华街交叉口东侧",
            "event": "夜间道路照明设施故障",
            "occurred_at_text": "昨日夜间 20:30 起",
            "target": "市政路灯养护所",
            "contact": "13800138002",
            "source": "web",
            "priority": "normal",
            "status": "pending",
            "creator_user_id": citizen_id,
            "category_id": _cat("CSGL-GGSS-LD"),
            "collaboration_status": "none",
            "created_at": t2_created,
            "accept_due_at": now + timedelta(hours=24),
            "resolve_due_at": now + timedelta(hours=72),
            "version": 1,
            "history": [
                ("create", None, "pending", citizen_id, "市民提交路灯故障投诉", "public", t2_created),
            ],
            "work_orders": [],
        },
        {
            "ticket_id": "QT2026110000000003",
            "idempotency_key": "seed-demo-ticket-0003",
            "request_type": "求助",
            "description": "东湖公园南门人行道附近雨水井盖松动翘起，存在行人绊倒隐患。",
            "location": "东湖公园南门人行道",
            "event": "雨水井盖松动存在安全隐患",
            "occurred_at_text": "今日清晨 07:30",
            "target": "市政设施巡查队",
            "contact": "13800138003",
            "source": "web",
            "priority": "expedited",
            "requested_priority": "urgent",
            "status": "pending",
            "needs_supplement": True,
            "supplement_reason": "请补充具体路口方位参照物及井盖编号或现场照片，便于应急抢修车快速定位。",
            "supplement_requested_at": now - timedelta(hours=1),
            "creator_user_id": citizen_id,
            "category_id": _cat("CSGL-GGSS-JG"),
            "collaboration_status": "awaiting_citizen",
            "created_at": t3_created,
            "accept_due_at": now + timedelta(hours=3),
            "resolve_due_at": now + timedelta(hours=24),
            "version": 2,
            "history": [
                ("create", None, "pending", citizen_id, "市民提交井盖隐患求助", "public", t3_created),
                ("request_supplement", "pending", "pending", agent_id, "坐席退回请市民补充具体方位信息", "public", now - timedelta(hours=1)),
            ],
            "work_orders": [],
        },
        {
            "ticket_id": "QT2026110000000004",
            "idempotency_key": "seed-demo-ticket-0004",
            "request_type": "投诉",
            "description": "人民西路 88 号公交站台前非机动车道出现约 2 米长路面沉降破损，雨天积水溅湿行人。",
            "location": "人民西路 88 号公交站台前非机动车道",
            "event": "非机动车道路面破损积水",
            "occurred_at_text": "近 3 日持续存在",
            "target": "市政道路养护中心",
            "contact": "13800138004",
            "source": "web",
            "priority": "expedited",
            "status": "accepted",
            "creator_user_id": citizen_id,
            "category_id": _cat("CSGL-GGSS-DL"),
            "collaboration_status": "none",
            "created_at": t4_created,
            "accepted_at": t4_accepted,
            "accept_due_at": t4_created + timedelta(hours=2),
            "resolve_due_at": now + timedelta(hours=3, minutes=20),
            "version": 2,
            "history": [
                ("create", None, "pending", citizen_id, "市民提交道路破损投诉", "public", t4_created),
                ("accept", "pending", "accepted", agent_id, "坐席已核验受理，待派发道路养护部门", "public", t4_accepted),
            ],
            "work_orders": [],
        },
        {
            "ticket_id": "QT2026110000000005",
            "idempotency_key": "seed-demo-ticket-0005",
            "request_type": "建议",
            "description": "建议及时清理文昌路农贸市场北侧人行道长期占道堆放的废旧装修物料，恢复无障碍通行。",
            "location": "文昌路农贸市场北侧人行道",
            "event": "占道堆物影响通行建议清理",
            "occurred_at_text": "近一周早晚高峰均可见",
            "target": "街道综合执法中队",
            "contact": "13900139005",
            "source": "web_anonymous",
            "anonymous_creator_key": "web-anon-demo-05",
            "priority": "urgent",
            "status": "accepted",
            "category_id": _cat("CSGL-HW-ZW"),
            "collaboration_status": "awaiting_dispatch",
            "dispatch_return_reason": "现场核查发现堆放区域位于区交界绿地退线内，建议重新核定牵头执法单位后改派。",
            "created_at": t5_created,
            "accepted_at": t5_accepted,
            "accept_due_at": t5_created + timedelta(hours=2),
            "resolve_due_at": now - timedelta(hours=5),
            "version": 3,
            "history": [
                ("create", None, "pending", None, "匿名市民提交占道堆物清理建议", "public", t5_created),
                ("accept", "pending", "accepted", agent_id, "坐席受理工单", "public", t5_accepted),
                ("assign", "accepted", "assigned", agent_id, "首次派发城市管理部门", "internal", t5_accepted + timedelta(minutes=15)),
                ("return_to_agent", "assigned", "accepted", dept_user_id, "部门核查退回坐席重新派发", "internal", t5_accepted + timedelta(hours=3)),
            ],
            "work_orders": [
                {
                    "work_order_no": "QT2026110000000005-M-1",
                    "task_type": "primary",
                    "status": "returned",
                    "department_id": _dept("urban-management"),
                    "instructions": "请现场核查占道堆物权属并责令限期清理。",
                    "return_reason": "堆放区域跨区界绿化带，请坐席协调改派综合执法牵头。",
                    "created_by_user_id": agent_id,
                    "history": [
                        ("create", None, "pending", agent_id, "派发城市管理主办任务", t5_accepted + timedelta(minutes=15)),
                        ("return_to_agent", "pending", "returned", dept_user_id, "权属界限需确认，退回坐席重新派发", t5_accepted + timedelta(hours=3)),
                    ],
                },
            ],
        },
        {
            "ticket_id": "QT2026110000000006",
            "idempotency_key": "seed-demo-ticket-0006",
            "request_type": "投诉",
            "description": "翠微园小区 3 号楼二次供水加压泵昨晚起水压明显不足，高楼层早高峰无法正常用水。",
            "location": "翠微园小区 3 号楼",
            "event": "高楼层供水压力不足",
            "occurred_at_text": "昨晚 21:00 至今",
            "target": "供水保障与综合协调专班",
            "contact": "13800138006",
            "source": "web",
            "priority": "normal",
            "status": "assigned",
            "creator_user_id": citizen_id,
            "assigned_department_id": _dept("general-intake"),
            "assigned_user_id": dept_user_id,
            "category_id": _cat("CSGL-GS-TS"),
            "collaboration_status": "in_progress",
            "created_at": t6_created,
            "accepted_at": t6_accepted,
            "accept_due_at": t6_created + timedelta(hours=1),
            "resolve_due_at": now + timedelta(hours=36),
            "version": 3,
            "history": [
                ("create", None, "pending", citizen_id, "市民提交二次供水压力不足投诉", "public", t6_created),
                ("accept", "pending", "accepted", agent_id, "坐席受理", "public", t6_accepted),
                ("assign", "accepted", "assigned", agent_id, "已派发综合受理部门（待部门接办）", "public", t6_accepted + timedelta(minutes=15)),
            ],
            "work_orders": [
                {
                    "work_order_no": "QT2026110000000006-M-1",
                    "task_type": "primary",
                    "status": "pending",
                    "department_id": _dept("general-intake"),
                    "assignee_user_id": dept_user_id,
                    "instructions": "请联动物业及水务公司排查 3 号楼二次供水泵房变频稳压设备。",
                    "created_by_user_id": agent_id,
                    "history": [
                        ("create", None, "pending", agent_id, "创建综合受理主办任务，待签收办理", t6_accepted + timedelta(minutes=15)),
                    ],
                },
            ],
        },
        {
            "ticket_id": "QT2026110000000007",
            "idempotency_key": "seed-demo-ticket-0007",
            "request_type": "建议",
            "description": "建议在高新二路地铁 B 口新增高峰期微循环接驳公交停靠标志牌并优化早高峰发车间隔。",
            "location": "高新二路地铁站 B 口",
            "event": "地铁口公交接驳站牌及班次优化建议",
            "occurred_at_text": "工作日早高峰 07:45-08:45",
            "target": "市交通运输局公交运营科",
            "contact": "13800138007",
            "source": "web",
            "priority": "expedited",
            "status": "assigned",
            "creator_user_id": citizen_id,
            "assigned_department_id": _dept("transport"),
            "category_id": _cat("CSGL-GGSS-DL"),
            "collaboration_status": "in_progress",
            "created_at": t7_created,
            "accepted_at": t7_accepted,
            "accept_due_at": t7_created + timedelta(hours=2),
            "resolve_due_at": now + timedelta(hours=2, minutes=30),
            "version": 3,
            "history": [
                ("create", None, "pending", citizen_id, "市民提交公交接驳建议", "public", t7_created),
                ("accept", "pending", "accepted", agent_id, "坐席受理并设为加急", "public", t7_accepted),
                ("assign", "accepted", "assigned", agent_id, "派发交通运输部门核研", "public", t7_accepted + timedelta(minutes=12)),
            ],
            "work_orders": [
                {
                    "work_order_no": "QT2026110000000007-M-1",
                    "task_type": "primary",
                    "status": "pending",
                    "department_id": _dept("transport"),
                    "instructions": "请结合早高峰客流监测评估接驳站点及班次优化方案。",
                    "created_by_user_id": agent_id,
                    "history": [
                        ("create", None, "pending", agent_id, "派发交通运输主办任务", t7_accepted + timedelta(minutes=12)),
                    ],
                },
            ],
        },
        {
            "ticket_id": "QT2026110000000008",
            "idempotency_key": "seed-demo-ticket-0008",
            "request_type": "投诉",
            "description": "滨河小区西门垃圾分类转运点连续四天未及时清运，厨余垃圾渗滤液外溢并伴随异味。",
            "location": "滨河小区西门垃圾分类转运点",
            "event": "生活垃圾滞留外溢异味投诉",
            "occurred_at_text": "已持续 4 天",
            "target": "环卫清运中心及街道办事处",
            "contact": "13800138008",
            "source": "web",
            "priority": "major",
            "status": "processing",
            "creator_user_id": citizen_id,
            "assigned_department_id": _dept("urban-management"),
            "category_id": _cat("CSGL-HW-LJ"),
            "collaboration_status": "in_progress",
            "created_at": t8_created,
            "accepted_at": t8_accepted,
            "accept_due_at": t8_created + timedelta(hours=2),
            "resolve_due_at": now - timedelta(hours=8),
            "version": 4,
            "history": [
                ("create", None, "pending", citizen_id, "市民上传现场照片并提交重大环卫投诉", "public", t8_created),
                ("accept", "pending", "accepted", agent_id, "坐席受理并升级为重大优先", "public", t8_accepted),
                ("assign", "accepted", "assigned", agent_id, "派发城市管理主办、综合受理协办", "public", t8_accepted + timedelta(minutes=15)),
                ("process", "assigned", "processing", dept_user_id, "主协办部门联合开展清运消杀与台账核查", "public", t8_accepted + timedelta(hours=1)),
            ],
            "work_orders": [
                {
                    "work_order_no": "QT2026110000000008-M-1",
                    "task_type": "primary",
                    "status": "processing",
                    "department_id": _dept("urban-management"),
                    "instructions": "立即调度清运车辆完成积存垃圾清理并冲洗地面渗滤液。",
                    "created_by_user_id": agent_id,
                    "accepted_at": t8_accepted + timedelta(hours=1),
                    "history": [
                        ("create", None, "pending", agent_id, "创建城市管理主办工单", t8_accepted + timedelta(minutes=15)),
                        ("start", "pending", "processing", agent_id, "城市管理处接单处置中", t8_accepted + timedelta(hours=1)),
                    ],
                },
                {
                    "work_order_no": "QT2026110000000008-C-1",
                    "task_type": "support",
                    "status": "processing",
                    "department_id": _dept("general-intake"),
                    "assignee_user_id": dept_user_id,
                    "instructions": "请协助对接属地物业明确转运站日常保洁责任界面。",
                    "created_by_user_id": agent_id,
                    "accepted_at": t8_accepted + timedelta(hours=1, minutes=10),
                    "history": [
                        ("create", None, "pending", agent_id, "创建综合受理协办工单", t8_accepted + timedelta(minutes=15)),
                        ("start", "pending", "processing", dept_user_id, "综合受理窗口协调物业核查中", t8_accepted + timedelta(hours=1, minutes=10)),
                    ],
                },
            ],
        },
        {
            "ticket_id": "QT2026110000000009",
            "idempotency_key": "seed-demo-ticket-0009",
            "request_type": "投诉",
            "description": "金桂苑地下车库出入口排水沟长期淤堵，暴雨后形成 15 厘米深积水影响车辆通行。",
            "location": "金桂苑小区地下车库北出口",
            "event": "车库排水沟淤堵积水",
            "occurred_at_text": "前日降雨后持续积水",
            "target": "金桂苑物业服务中心",
            "contact": "13800138009",
            "source": "web",
            "priority": "normal",
            "status": "processing",
            "creator_user_id": citizen_id,
            "assigned_department_id": _dept("housing-property"),
            "category_id": _cat("CSGL-GS-JS"),
            "collaboration_status": "awaiting_summary",
            "created_at": t9_created,
            "accepted_at": t9_accepted,
            "accept_due_at": t9_created + timedelta(hours=1),
            "resolve_due_at": now + timedelta(hours=40),
            "version": 5,
            "history": [
                ("create", None, "pending", citizen_id, "市民提交车库积水投诉", "public", t9_created),
                ("accept", "pending", "accepted", agent_id, "坐席受理", "public", t9_accepted),
                ("assign", "accepted", "assigned", agent_id, "派发住房物业主办、综合受理协办", "public", t9_accepted + timedelta(minutes=20)),
                ("process", "assigned", "processing", dept_user_id, "主协办均已提交阶段处置结果，待主办方汇总上报", "public", t9_accepted + timedelta(hours=6)),
            ],
            "work_orders": [
                {
                    "work_order_no": "QT2026110000000009-M-1",
                    "task_type": "primary",
                    "status": "submitted",
                    "department_id": _dept("housing-property"),
                    "instructions": "督促物业开展雨水篦子清掏和潜污泵检修。",
                    "result_summary": "已责成物业完成淤泥清掏并更换 2 台排水泵。",
                    "result_measures": "疏通排水明沟 65 米，增设高水位报警浮球。",
                    "result_outcome": "resolved",
                    "public_content": "小区车库出口积水已抽排清理并完成泵站检修。",
                    "created_by_user_id": agent_id,
                    "accepted_at": t9_accepted + timedelta(hours=1),
                    "submitted_at": t9_accepted + timedelta(hours=6),
                    "history": [
                        ("create", None, "pending", agent_id, "创建住房物业主办任务", t9_accepted + timedelta(minutes=20)),
                        ("submit_result", "processing", "submitted", agent_id, "主办部门已提交现场清掏结果", t9_accepted + timedelta(hours=6)),
                    ],
                },
                {
                    "work_order_no": "QT2026110000000009-C-1",
                    "task_type": "support",
                    "status": "submitted",
                    "department_id": _dept("general-intake"),
                    "assignee_user_id": dept_user_id,
                    "instructions": "配合核查市政雨水管网接驳口通畅情况。",
                    "result_summary": "市政支管网接驳口畅通无倒灌。",
                    "result_measures": "联合市政管网巡检队开井核验管网液位。",
                    "result_outcome": "resolved",
                    "public_content": "外网市政接驳口核验正常。",
                    "created_by_user_id": agent_id,
                    "accepted_at": t9_accepted + timedelta(hours=1),
                    "submitted_at": t9_accepted + timedelta(hours=5),
                    "history": [
                        ("create", None, "pending", agent_id, "创建综合受理协办任务", t9_accepted + timedelta(minutes=20)),
                        ("submit_result", "processing", "submitted", dept_user_id, "协办部门提交管网核验结果", t9_accepted + timedelta(hours=5)),
                    ],
                },
            ],
        },
        {
            "ticket_id": "QT2026110000000010",
            "idempotency_key": "seed-demo-ticket-0010",
            "request_type": "求助",
            "description": "学府巷老旧小区 2 单元楼道公共照明及应急电源箱跳闸停电，晚间老人上下楼不便。",
            "location": "学府巷 14 号院 2 单元",
            "event": "老旧小区楼道公共供电故障",
            "occurred_at_text": "本周初起频繁跳闸",
            "target": "供电应急保障联席办",
            "contact": "13800138010",
            "source": "web",
            "priority": "expedited",
            "status": "processing",
            "creator_user_id": citizen_id,
            "assigned_department_id": _dept("general-intake"),
            "assigned_user_id": dept_user_id,
            "category_id": _cat("CSGL-GGSS-GD"),
            "collaboration_status": "awaiting_review",
            "review_draft": {
                "resolution_summary": "已完成学府巷 14 号院 2 单元公共照明配电箱空开更换及老化线路整治，楼道照明恢复正常。",
                "resolution_measures": "1. 联合街道电工与供电抢修班现场排查漏电支路；2. 更换 32A 漏电保护器并重接 1-6 层感应灯线路；3. 张贴安全用电提示。",
                "resolution_outcome": "resolved",
                "public_reply": "您好，您反映的学府巷 14 号院 2 单元楼道公共供电跳闸问题，经现场更换漏电保护器并整修受潮线路后已恢复稳定供电，楼道照明正常。",
                "internal_note": "已附供电维修确认单 PDF，提请坐席/管理员复核办结。",
            },
            "created_at": t10_created,
            "accepted_at": t10_accepted,
            "accept_due_at": t10_created + timedelta(hours=1),
            "resolve_due_at": now + timedelta(hours=3),
            "version": 5,
            "history": [
                ("create", None, "pending", citizen_id, "市民提交楼道供电故障求助", "public", t10_created),
                ("accept", "pending", "accepted", agent_id, "坐席受理", "public", t10_accepted),
                ("assign", "accepted", "assigned", agent_id, "派发综合受理统筹供电应急维修", "public", t10_accepted + timedelta(minutes=20)),
                ("submit_for_review", "processing", "processing", dept_user_id, "部门提交办结汇总草稿，等待坐席复核", "public", now - timedelta(hours=4)),
            ],
            "work_orders": [
                {
                    "work_order_no": "QT2026110000000010-M-1",
                    "task_type": "primary",
                    "status": "submitted",
                    "department_id": _dept("general-intake"),
                    "assignee_user_id": dept_user_id,
                    "instructions": "请协调街道电工与供电所核查楼道照明跳闸隐患并形成整改确认单。",
                    "result_summary": "已更换漏电保护开关并恢复楼道供电。",
                    "result_measures": "排查受潮线盒 3 处并更换防潮接线端子。",
                    "result_outcome": "resolved",
                    "public_content": "学府巷 14 号院 2 单元楼道供电已恢复稳定。",
                    "created_by_user_id": agent_id,
                    "accepted_at": t10_accepted + timedelta(minutes=40),
                    "submitted_at": now - timedelta(hours=4),
                    "history": [
                        ("create", None, "pending", agent_id, "派发综合受理主办工单", t10_accepted + timedelta(minutes=20)),
                        ("start", "pending", "processing", dept_user_id, "部门接办并联动电工排查", t10_accepted + timedelta(minutes=40)),
                        ("submit_result", "processing", "submitted", dept_user_id, "提交维修确认单并进入待复核", now - timedelta(hours=4)),
                    ],
                },
            ],
        },
        {
            "ticket_id": "QT2026110000000011",
            "idempotency_key": "seed-demo-ticket-0011",
            "request_type": "投诉",
            "description": "梧桐大道 32 号院门前大型法桐因大风倾斜压靠架空线缆，需园林专家评估后停电修剪。",
            "location": "梧桐大道 32 号院门前",
            "event": "行道树倾斜压线隐患（SLA暂停及复核退回）",
            "occurred_at_text": "大风天气后持续倾斜",
            "target": "园林应急抢险队",
            "contact": "13800138011",
            "source": "web",
            "priority": "urgent",
            "status": "processing",
            "creator_user_id": citizen_id,
            "assigned_department_id": _dept("general-intake"),
            "assigned_user_id": dept_user_id,
            "category_id": _cat("CSGL-YL-SM"),
            "collaboration_status": "in_progress",
            "sla_paused_at": now - timedelta(hours=2),
            "sla_pause_reason": "需供电公司安排计划停电窗口并由园林安全专家现场评估倒伏风险，SLA 计时依法暂停。",
            "total_paused_seconds": 7200,
            "created_at": t11_created,
            "accepted_at": t11_accepted,
            "accept_due_at": t11_created + timedelta(hours=1),
            "resolve_due_at": now + timedelta(hours=24),
            "version": 6,
            "history": [
                ("create", None, "pending", citizen_id, "市民投诉行道树倾斜压线", "public", t11_created),
                ("accept", "pending", "accepted", agent_id, "坐席紧急受理", "public", t11_accepted),
                ("assign", "accepted", "assigned", agent_id, "派发综合受理统筹安全排险", "public", t11_accepted + timedelta(minutes=15)),
                ("return_to_department", "processing", "processing", agent_id, "复核退回：请补充树体安全鉴定结论及停电排险计划", "internal", now - timedelta(hours=3)),
                ("pause_sla", "processing", "processing", agent_id, "因等待电力停电作业窗口，已暂停 SLA 计时", "public", now - timedelta(hours=2)),
            ],
            "work_orders": [
                {
                    "work_order_no": "QT2026110000000011-M-1",
                    "task_type": "primary",
                    "status": "processing",
                    "department_id": _dept("general-intake"),
                    "assignee_user_id": dept_user_id,
                    "instructions": "请协调园林绿化与供电局开展带电安全评估并制定排险修剪方案。",
                    "return_reason": "复核退回：原提交方案缺少架空线缆停电配合时间表，请补充完善后重报。",
                    "created_by_user_id": agent_id,
                    "accepted_at": t11_accepted + timedelta(minutes=30),
                    "history": [
                        ("create", None, "pending", agent_id, "创建综合受理主办工单", t11_accepted + timedelta(minutes=15)),
                        ("start", "pending", "processing", dept_user_id, "部门组织现场警戒围挡", t11_accepted + timedelta(minutes=30)),
                        ("submit_result", "processing", "submitted", dept_user_id, "首次提交临时支撑处理说明", now - timedelta(hours=5)),
                        ("return_to_department", "submitted", "processing", agent_id, "复核退回部门补充安全评估与停电配合计划", now - timedelta(hours=3)),
                    ],
                },
            ],
        },
        {
            "ticket_id": "QT2026110000000012",
            "idempotency_key": "seed-demo-ticket-0012",
            "request_type": "求助",
            "description": "育才实验小学北侧围墙外绿化带灌木枝条遮挡校门口斑马线视野，申诉要求彻底修剪并增设警示。",
            "location": "育才实验小学北门斑马线旁",
            "event": "校园周边绿化遮挡视线申诉重办",
            "occurred_at_text": "接送学时段存在视线盲区",
            "target": "教育安全协调办及园林养护单位",
            "contact": "13800138012",
            "source": "web",
            "priority": "normal",
            "status": "processing",
            "creator_user_id": citizen_id,
            "assigned_department_id": _dept("education"),
            "category_id": _cat("CSGL-YL-LH"),
            "collaboration_status": "in_progress",
            "handling_round": 2,
            "appeal_count": 1,
            "created_at": t12_created,
            "accepted_at": t12_accepted,
            "accept_due_at": t12_created + timedelta(hours=2),
            "resolve_due_at": now + timedelta(hours=52),
            "version": 7,
            "history": [
                ("create", None, "pending", citizen_id, "市民提交校园周边视野遮挡求助", "public", t12_created),
                ("accept", "pending", "accepted", agent_id, "坐席受理", "public", t12_accepted),
                ("resolve", "processing", "resolved", agent_id, "第 1 轮修剪后办结", "public", t12_created + timedelta(days=2)),
                ("submit_appeal", "resolved", "resolved", citizen_id, "市民提交第 1 次申诉：东侧转角仍有遮挡", "public", t12_created + timedelta(days=3)),
                ("appeal_approved", "resolved", "processing", admin_id, "管理员审批通过申诉，进入第 2 轮重办并加派复核任务", "public", now - timedelta(days=1)),
            ],
            "work_orders": [
                {
                    "work_order_no": "QT2026110000000012-M-2",
                    "task_type": "primary",
                    "status": "processing",
                    "department_id": _dept("education"),
                    "instructions": "请教育部门会同学校对北门东侧转角灌木做低矮化修剪并核验视野通透度。",
                    "created_by_user_id": admin_id,
                    "accepted_at": now - timedelta(hours=18),
                    "history": [
                        ("appeal_reprocess", None, "processing", admin_id, "申诉重办第 2 轮主办工单启动", now - timedelta(hours=18)),
                    ],
                },
                {
                    "work_order_no": "QT2026110000000012-R-2",
                    "task_type": "review",
                    "status": "pending",
                    "department_id": _dept("general-intake"),
                    "assignee_user_id": dept_user_id,
                    "instructions": "请综合受理窗口作为复核协办方实地抽验修剪后通行视野。",
                    "created_by_user_id": admin_id,
                    "history": [
                        ("create", None, "pending", admin_id, "派发申诉复核协办任务，待综合受理接办", now - timedelta(hours=18)),
                    ],
                },
            ],
        },
        {
            "ticket_id": "QT2026110000000013",
            "idempotency_key": "seed-demo-ticket-0013",
            "request_type": "咨询",
            "description": "咨询南湖社区卫生服务中心秋季老年人免费流感疫苗接种预约流程及周六开诊时段。",
            "location": "南湖社区卫生服务中心",
            "event": "社区医疗便民服务接种时间咨询",
            "occurred_at_text": "本月接种周期",
            "target": "市卫健委基层医疗科",
            "contact": "13800138013",
            "source": "web",
            "priority": "normal",
            "status": "resolved",
            "creator_user_id": citizen_id,
            "assigned_department_id": _dept("health"),
            "category_id": _cat("CSGL-GGSS-LD"),
            "collaboration_status": "completed",
            "resolution_summary": "已核实并向市民公布南湖社区卫生服务中心接种时间及线上线下双通道预约方式。",
            "resolution_measures": "核对卫健基层科最新门诊排班，明确周六上午 08:30-11:30 开放老年人专场接种。",
            "resolution_outcome": "resolved",
            "public_reply": "您好，南湖社区卫生服务中心每周二、四、六上午 08:30-11:30 开放 60 岁以上户籍/常住老年人免费流感疫苗接种，可凭身份证现场取号或通过市健康服务小程序提前预约。",
            "created_at": t13_created,
            "accepted_at": t13_accepted,
            "resolved_at": t13_resolved,
            "accept_due_at": t13_created + timedelta(hours=2),
            "resolve_due_at": t13_created + timedelta(hours=48),
            "version": 4,
            "history": [
                ("create", None, "pending", citizen_id, "市民提交社区接种服务咨询", "public", t13_created),
                ("accept", "pending", "accepted", agent_id, "坐席受理", "public", t13_accepted),
                ("assign", "accepted", "assigned", agent_id, "派发医疗卫生部门", "public", t13_accepted + timedelta(minutes=15)),
                ("resolve", "processing", "resolved", agent_id, "答复已生成，等待市民确认评价", "public", t13_resolved),
            ],
            "work_orders": [
                {
                    "work_order_no": "QT2026110000000013-M-1",
                    "task_type": "primary",
                    "status": "submitted",
                    "department_id": _dept("health"),
                    "instructions": "核实最新门诊排班及预约渠道并答复市民。",
                    "result_summary": "已核实周六上午专场接种排班。",
                    "result_outcome": "resolved",
                    "public_content": "已提供详细接种时段及预约渠道。",
                    "created_by_user_id": agent_id,
                    "accepted_at": t13_accepted + timedelta(minutes=45),
                    "submitted_at": t13_resolved - timedelta(hours=1),
                    "completed_at": t13_resolved,
                    "history": [
                        ("create", None, "pending", agent_id, "派发医疗卫生主办任务", t13_accepted + timedelta(minutes=15)),
                        ("submit_result", "processing", "submitted", agent_id, "医疗卫生部门提交完整答复", t13_resolved - timedelta(hours=1)),
                    ],
                },
            ],
        },
        {
            "ticket_id": "QT2026110000000014",
            "idempotency_key": "seed-demo-ticket-0014",
            "request_type": "投诉",
            "description": "康乐家园东区老年人助餐点周边晚间厨余垃圾桶占道堆放且清运不及时，影响一楼住户开窗通风。",
            "location": "康乐家园东区 1 号楼南侧",
            "event": "社区助餐点垃圾清运频次投诉及申诉",
            "occurred_at_text": "每日晚间 19:00 后",
            "target": "社区居委会及保洁单位",
            "contact": "13800138014",
            "source": "web",
            "priority": "normal",
            "status": "resolved",
            "creator_user_id": citizen_id,
            "assigned_department_id": _dept("community-civil"),
            "category_id": _cat("CSGL-HW-LJ"),
            "collaboration_status": "completed",
            "resolution_summary": "已要求社区助餐点在晚餐收餐后及时加盖并将垃圾桶移回封闭暂存间。",
            "resolution_measures": "约谈助餐点运营方并增加晚间 20:00 清运班次检查。",
            "resolution_outcome": "partially_resolved",
            "public_reply": "您好，已督促助餐点将垃圾桶移回指定暂存区并落实加盖要求，社区网格员将加强晚间巡查。",
            "appeal_count": 1,
            "created_at": t14_created,
            "accepted_at": t14_accepted,
            "resolved_at": t14_resolved,
            "accept_due_at": t14_created + timedelta(hours=2),
            "resolve_due_at": t14_created + timedelta(hours=48),
            "version": 5,
            "history": [
                ("create", None, "pending", citizen_id, "市民提交社区环境卫生投诉", "public", t14_created),
                ("accept", "pending", "accepted", agent_id, "坐席受理", "public", t14_accepted),
                ("resolve", "processing", "resolved", agent_id, "部门提交整改回复", "public", t14_resolved),
                ("citizen_feedback", "resolved", "resolved", citizen_id, "市民评价不满意：晚间仍有异味", "public", t14_resolved + timedelta(hours=10)),
                ("submit_appeal", "resolved", "resolved", citizen_id, "市民提交第 1 次申诉，等待管理员审核", "public", t14_resolved + timedelta(hours=12)),
            ],
            "work_orders": [
                {
                    "work_order_no": "QT2026110000000014-M-1",
                    "task_type": "primary",
                    "status": "submitted",
                    "department_id": _dept("community-civil"),
                    "instructions": "督促社区助餐点规范垃圾桶存放并加盖清运。",
                    "result_summary": "已约定晚间收餐后统一归位暂存间。",
                    "result_outcome": "partially_resolved",
                    "public_content": "社区将加强晚间保洁巡查频次。",
                    "created_by_user_id": agent_id,
                    "accepted_at": t14_accepted + timedelta(hours=1),
                    "submitted_at": t14_resolved - timedelta(hours=2),
                    "completed_at": t14_resolved,
                    "history": [
                        ("create", None, "pending", agent_id, "派发社区民政主办任务", t14_accepted + timedelta(minutes=20)),
                        ("submit_result", "processing", "submitted", agent_id, "提交阶段整改结果", t14_resolved - timedelta(hours=2)),
                    ],
                },
            ],
        },
        {
            "ticket_id": "QT2026110000000015",
            "idempotency_key": "seed-demo-ticket-0015",
            "request_type": "投诉",
            "description": "青云路中段 12 号至 18 号路段夜间路灯全段熄灭，造成沿线商铺及居民通行不便。",
            "location": "青云路中段 12-18 号",
            "event": "成片路灯熄灭故障抢修",
            "occurred_at_text": "11 天前夜间",
            "target": "市政路灯抢修班",
            "contact": "13800138015",
            "source": "web",
            "priority": "normal",
            "status": "closed",
            "closure_type": "citizen_confirmed",
            "creator_user_id": citizen_id,
            "assigned_department_id": _dept("urban-management"),
            "category_id": _cat("CSGL-GGSS-LD"),
            "collaboration_status": "completed",
            "resolution_summary": "已修复青云路中段地下电缆接头故障，全段 14 盏路灯恢复正常亮灯。",
            "resolution_measures": "使用故障仪定位 16 号杆地下电缆断点并重新压接防水接头。",
            "resolution_outcome": "resolved",
            "public_reply": "您好，青云路中段路灯控制箱及地下电缆接头已抢修完毕，夜间测试照度达标并已恢复正常照明。",
            "appeal_count": 1,
            "created_at": t15_created,
            "accepted_at": t15_accepted,
            "resolved_at": t15_resolved,
            "closed_at": t15_closed,
            "accept_due_at": t15_created + timedelta(hours=1),
            "resolve_due_at": t15_created + timedelta(hours=24),
            "version": 6,
            "history": [
                ("create", None, "pending", citizen_id, "市民提交路灯故障投诉", "public", t15_created),
                ("accept", "pending", "accepted", agent_id, "坐席受理", "public", t15_accepted),
                ("resolve", "processing", "resolved", agent_id, "抢修完成等待市民评价", "public", t15_resolved),
                ("close", "resolved", "closed", citizen_id, "市民评价满意并确认办结", "public", t15_closed),
            ],
            "work_orders": [
                {
                    "work_order_no": "QT2026110000000015-M-1",
                    "task_type": "primary",
                    "status": "submitted",
                    "department_id": _dept("urban-management"),
                    "instructions": "排查青云路中段路灯回路并完成电缆抢修。",
                    "result_summary": "已修复电缆接头并全线亮灯。",
                    "result_outcome": "resolved",
                    "public_content": "青云路中段路灯已恢复正常运行。",
                    "created_by_user_id": agent_id,
                    "accepted_at": t15_accepted + timedelta(minutes=30),
                    "submitted_at": t15_resolved - timedelta(hours=1),
                    "completed_at": t15_resolved,
                    "history": [
                        ("create", None, "pending", agent_id, "派发城市管理主办任务", t15_accepted + timedelta(minutes=10)),
                        ("submit_result", "processing", "submitted", agent_id, "提交抢修验收结果", t15_resolved - timedelta(hours=1)),
                    ],
                },
            ],
        },
        {
            "ticket_id": "QT2026110000000016",
            "idempotency_key": "seed-demo-ticket-0016",
            "request_type": "建议",
            "description": "建议维修星海广场西侧公交候车亭破损顶棚玻璃并增设夜间防滑盲道提示。",
            "location": "星海广场西侧公交站",
            "event": "公交候车亭设施修缮建议",
            "occurred_at_text": "12 天前反映",
            "target": "公交场站运维中心",
            "contact": "13900139016",
            "source": "web_anonymous",
            "anonymous_creator_key": "web-anon-demo-16",
            "priority": "normal",
            "status": "closed",
            "closure_type": "phone_confirmed",
            "assigned_department_id": _dept("transport"),
            "category_id": _cat("CSGL-GGSS-DL"),
            "collaboration_status": "completed",
            "resolution_summary": "已更换候车亭钢化顶棚并完成站台盲道防滑条修复。",
            "resolution_measures": "拆除破损夹胶玻璃并安装防爆聚碳酸酯雨棚，补齐 8 米止滑盲道砖。",
            "resolution_outcome": "resolved",
            "public_reply": "您好，星海广场西侧公交站候车亭顶棚及站台防滑盲道均已修缮完毕，感谢您的宝贵建议。",
            "created_at": t16_created,
            "accepted_at": t16_accepted,
            "resolved_at": t16_resolved,
            "closed_at": t16_closed,
            "accept_due_at": t16_created + timedelta(hours=2),
            "resolve_due_at": t16_created + timedelta(hours=48),
            "version": 5,
            "history": [
                ("create", None, "pending", None, "匿名市民提交公交候车亭修缮建议", "public", t16_created),
                ("accept", "pending", "accepted", agent_id, "坐席受理", "public", t16_accepted),
                ("resolve", "processing", "resolved", agent_id, "交通运输部门完成修缮", "public", t16_resolved),
                ("phone_follow_up_close", "resolved", "closed", agent_id, "坐席电话回访市民确认满意并办结", "public", t16_closed),
            ],
            "work_orders": [
                {
                    "work_order_no": "QT2026110000000016-M-1",
                    "task_type": "primary",
                    "status": "submitted",
                    "department_id": _dept("transport"),
                    "instructions": "修缮星海广场公交候车亭顶棚并核查盲道安全。",
                    "result_summary": "顶棚及防滑盲道均已更换验收。",
                    "result_outcome": "resolved",
                    "public_content": "候车亭修缮工程已完成。",
                    "created_by_user_id": agent_id,
                    "accepted_at": t16_accepted + timedelta(hours=1),
                    "submitted_at": t16_resolved - timedelta(hours=1),
                    "completed_at": t16_resolved,
                    "history": [
                        ("create", None, "pending", agent_id, "派发交通运输主办任务", t16_accepted + timedelta(minutes=20)),
                        ("submit_result", "processing", "submitted", agent_id, "提交修缮验收记录", t16_resolved - timedelta(hours=1)),
                    ],
                },
            ],
        },
        {
            "ticket_id": "QT2026110000000017",
            "idempotency_key": "seed-demo-ticket-0017",
            "request_type": "求助",
            "description": "阳光社区老年人活动室门前无障碍坡道坡度偏陡且缺少防滑条，申诉复核要求二次整改。",
            "location": "阳光社区服务中心东门",
            "event": "无障碍坡道整改申诉办结",
            "occurred_at_text": "13 天前提交",
            "target": "社区民政服务站",
            "contact": "13800138017",
            "source": "web",
            "priority": "expedited",
            "status": "closed",
            "closure_type": "admin_override",
            "creator_user_id": citizen_id,
            "assigned_department_id": _dept("community-civil"),
            "category_id": _cat("CSGL-YL-LH"),
            "collaboration_status": "completed",
            "handling_round": 2,
            "appeal_count": 1,
            "resolution_summary": "经二次整改已加长无障碍缓坡并铺设金刚砂防滑条与双侧扶手，验收合格。",
            "resolution_measures": "按无障碍设计规范将坡道比调整为 1:12，加装不锈钢双层扶手及防滑条。",
            "resolution_outcome": "resolved",
            "public_reply": "您好，阳光社区服务中心东门无障碍坡道已完成二次扩坡及防滑扶手加装工程，现已投入使用。",
            "created_at": t17_created,
            "accepted_at": t17_accepted,
            "resolved_at": t17_resolved,
            "closed_at": t17_closed,
            "accept_due_at": t17_created + timedelta(hours=2),
            "resolve_due_at": t17_created + timedelta(hours=24),
            "version": 7,
            "history": [
                ("create", None, "pending", citizen_id, "市民求助整改社区无障碍坡道", "public", t17_created),
                ("accept", "pending", "accepted", agent_id, "坐席受理", "public", t17_accepted),
                ("appeal_approved", "resolved", "processing", admin_id, "申诉通过并重新派发二次整改", "public", t17_created + timedelta(hours=26)),
                ("resolve", "processing", "resolved", admin_id, "二次整改验收合格", "public", t17_resolved),
                ("admin_close", "resolved", "closed", admin_id, "管理员复核确认办结归档", "public", t17_closed),
            ],
            "work_orders": [
                {
                    "work_order_no": "QT2026110000000017-M-2",
                    "task_type": "primary",
                    "status": "submitted",
                    "department_id": _dept("community-civil"),
                    "instructions": "按 1:12 坡度标准落实无障碍坡道二次整改。",
                    "result_summary": "坡道整改及扶手安装已完成验收。",
                    "result_outcome": "resolved",
                    "public_content": "已完成坡道防滑与坡度整改。",
                    "created_by_user_id": admin_id,
                    "accepted_at": t17_created + timedelta(hours=27),
                    "submitted_at": t17_resolved - timedelta(hours=1),
                    "completed_at": t17_resolved,
                    "history": [
                        ("appeal_reprocess", None, "processing", admin_id, "申诉二次整改派发", t17_created + timedelta(hours=27)),
                        ("submit_result", "processing", "submitted", agent_id, "社区民政提交二次整改验收材料", t17_resolved - timedelta(hours=1)),
                    ],
                },
            ],
        },
        {
            "ticket_id": "QT2026110000000018",
            "idempotency_key": "seed-demo-ticket-0018",
            "request_type": "投诉",
            "description": "反映京津高速 K42 收费站出省方向货车通行ETC车道识别延迟问题。",
            "location": "京津高速 K42 收费站",
            "event": "跨省高速公路收费站车道识别投诉（非市属管辖）",
            "occurred_at_text": "13 天前",
            "target": "高速公路运营公司",
            "contact": "13900139018",
            "source": "web_anonymous",
            "anonymous_creator_key": "web-anon-demo-18",
            "priority": "normal",
            "status": "rejected",
            "category_id": _cat("CSGL-GGSS-JG"),
            "collaboration_status": "none",
            "needs_supplement": False,
            "rejection_reason_code": "out_of_jurisdiction",
            "rejection_detail": "京津高速 K42 收费站属省级高速公路运营集团管辖，超出本市市政便民热线受理权限，已向来电人提供省级高速服务渠道指引。",
            "suggested_channel": "请拨打全国交通运输服务监督热线 12328 或联系省级高速公路客户服务中心。",
            "created_at": t18_created,
            "accept_due_at": t18_created + timedelta(hours=2),
            "version": 2,
            "history": [
                ("create", None, "pending", None, "匿名市民提交高速公路收费站投诉", "public", t18_created),
                ("reject", "pending", "rejected", agent_id, "非本市受理管辖范围，依法不予受理并指引转办渠道", "public", t18_created + timedelta(minutes=35)),
            ],
            "work_orders": [],
        },
    ]

    tickets_by_id: dict[str, TicketModel] = {}
    for spec in ticket_specs:
        tid = spec["ticket_id"]
        ticket = db.scalar(select(TicketModel).where(TicketModel.ticket_id == tid))
        if not ticket:
            ticket = TicketModel(
                ticket_id=tid,
                idempotency_key=spec["idempotency_key"],
                request_type=spec["request_type"],
                description=spec["description"],
                location=spec["location"],
                event=spec.get("event"),
                occurred_at_text=spec.get("occurred_at_text"),
                timezone="Asia/Shanghai",
                target=spec.get("target"),
                contact=spec.get("contact"),
                creator_user_id=spec.get("creator_user_id"),
                anonymous_creator_key=spec.get("anonymous_creator_key"),
                assigned_department_id=spec.get("assigned_department_id"),
                assigned_user_id=spec.get("assigned_user_id"),
                category_id=spec.get("category_id"),
                requested_priority=spec.get("requested_priority"),
                priority=spec["priority"],
                status=spec["status"],
                source=spec["source"],
                accepted_at=spec.get("accepted_at"),
                resolved_at=spec.get("resolved_at"),
                closed_at=spec.get("closed_at"),
                accept_due_at=spec.get("accept_due_at"),
                resolve_due_at=spec.get("resolve_due_at"),
                sla_paused_at=spec.get("sla_paused_at"),
                sla_pause_reason=spec.get("sla_pause_reason"),
                total_paused_seconds=spec.get("total_paused_seconds", 0),
                resolution_summary=spec.get("resolution_summary"),
                resolution_measures=spec.get("resolution_measures"),
                resolution_outcome=spec.get("resolution_outcome"),
                public_reply=spec.get("public_reply"),
                review_draft=spec.get("review_draft"),
                rejection_reason_code=spec.get("rejection_reason_code"),
                rejection_detail=spec.get("rejection_detail"),
                suggested_channel=spec.get("suggested_channel"),
                needs_supplement=spec.get("needs_supplement", False),
                supplement_reason=spec.get("supplement_reason"),
                supplement_requested_at=spec.get("supplement_requested_at"),
                dispatch_return_reason=spec.get("dispatch_return_reason"),
                closure_type=spec.get("closure_type"),
                handling_round=spec.get("handling_round", 1),
                appeal_count=spec.get("appeal_count", 0),
                collaboration_status=spec["collaboration_status"],
                version=spec["version"],
                created_at=spec["created_at"],
                updated_at=spec.get("closed_at") or spec.get("resolved_at") or spec.get("accepted_at") or spec["created_at"],
            )
            db.add(ticket)
            db.flush()
        else:
            # Idempotently enrich missing SLA/category/collaboration metadata (e.g. legacy QTDEMO000000000001).
            if ticket.category_id is None and spec.get("category_id") is not None:
                ticket.category_id = spec["category_id"]
            if ticket.accept_due_at is None and spec.get("accept_due_at") is not None:
                ticket.accept_due_at = spec["accept_due_at"]
            if ticket.resolve_due_at is None and spec.get("resolve_due_at") is not None:
                ticket.resolve_due_at = spec["resolve_due_at"]
            if ticket.event is None and spec.get("event") is not None:
                ticket.event = spec["event"]
            if ticket.occurred_at_text is None and spec.get("occurred_at_text") is not None:
                ticket.occurred_at_text = spec["occurred_at_text"]
            if ticket.target is None and spec.get("target") is not None:
                ticket.target = spec["target"]
            if ticket.contact is None and spec.get("contact") is not None:
                ticket.contact = spec["contact"]

        tickets_by_id[tid] = ticket

        has_history = db.scalar(
            select(TicketStatusHistoryModel.id)
            .where(TicketStatusHistoryModel.ticket_id == tid)
            .limit(1)
        )
        if not has_history:
            for op_type, prev_s, curr_s, op_uid, content, vis, ts in spec["history"]:
                db.add(
                    TicketStatusHistoryModel(
                        ticket_id=tid,
                        operator_user_id=op_uid,
                        operation_type=op_type,
                        content=content,
                        previous_status=prev_s,
                        current_status=curr_s,
                        remark=content,
                        visibility=vis,
                        created_at=ts,
                    )
                )

        for wo_spec in spec["work_orders"]:
            wo_no = wo_spec["work_order_no"]
            wo = db.scalar(select(WorkOrderModel).where(WorkOrderModel.work_order_no == wo_no))
            if not wo:
                if tid == "QTDEMO000000000001" and wo_spec["task_type"] == "primary":
                    existing_primary = db.scalar(
                        select(WorkOrderModel).where(
                            WorkOrderModel.ticket_id == tid,
                            WorkOrderModel.task_type == "primary",
                            WorkOrderModel.status.in_(("pending", "processing", "submitted")),
                        )
                    )
                    if existing_primary:
                        wo = existing_primary
                if not wo:
                    wo = WorkOrderModel(
                        id=_deterministic_uuid4(f"wo:{wo_no}"),
                        work_order_no=wo_no,
                        ticket_id=tid,
                        task_type=wo_spec["task_type"],
                        status=wo_spec["status"],
                        department_id=wo_spec["department_id"],
                        assignee_user_id=wo_spec.get("assignee_user_id"),
                        instructions=wo_spec["instructions"],
                        result_summary=wo_spec.get("result_summary"),
                        result_measures=wo_spec.get("result_measures"),
                        result_outcome=wo_spec.get("result_outcome"),
                        public_content=wo_spec.get("public_content"),
                        return_reason=wo_spec.get("return_reason"),
                        created_by_user_id=wo_spec.get("created_by_user_id"),
                        accepted_at=wo_spec.get("accepted_at"),
                        submitted_at=wo_spec.get("submitted_at"),
                        completed_at=wo_spec.get("completed_at"),
                        created_at=wo_spec["history"][0][5] if wo_spec["history"] else spec["created_at"],
                    )
                    db.add(wo)
                    db.flush()
            has_wo_history = db.scalar(
                select(WorkOrderHistoryModel.id)
                .where(WorkOrderHistoryModel.work_order_id == wo.id)
                .limit(1)
            )
            if not has_wo_history:
                for action, prev_s, curr_s, op_uid, content, ts in wo_spec["history"]:
                    db.add(
                        WorkOrderHistoryModel(
                            work_order_id=wo.id,
                            operator_user_id=op_uid,
                            action=action,
                            previous_status=prev_s,
                            current_status=curr_s,
                            content=content,
                            created_at=ts,
                        )
                    )
    db.flush()
    return tickets_by_id


def _seed_demo_attachments(
    db,
    users: dict[str, UserModel],
    department_ids: dict[str, int],
    tickets_by_id: dict[str, TicketModel],
    now: datetime,
) -> int:
    """Upload valid PDF/PNG demo attachments to MinIO and upsert clean DB records idempotently."""
    try:
        storage = storage_module.get_object_storage()
    except Exception as exc:
        logger.warning("Seed attachments skipped: object storage init failed: %s", exc)
        return 0

    try:
        from minio.error import S3Error
    except ImportError:
        S3Error = None  # type: ignore[assignment]

    road_pdf = _build_demo_pdf_bytes(
        "CivicEcho Evidence - Road Damage Report",
        [
            "Ticket ID: QT2026110000000004",
            "Location: Renmin West Rd #88 Bus Stop Bike Lane",
            "Category: Municipal Road Surface Settlement",
            "Status: Citizen Uploaded Evidence (Seed Verified)",
        ],
    )
    site_png = _build_demo_png_bytes()
    power_pdf = _build_demo_pdf_bytes(
        "CivicEcho Official Inspection - Power Repair",
        [
            "Ticket ID: QT2026110000000010",
            "Location: Xuefu Alley #14 Unit 2 Corridor Panel",
            "Action: Replaced 32A RCD Breaker and Moisture Terminals",
            "Result: Corridor Lighting Restored - Ready for Review",
        ],
    )

    attachment_specs = [
        {
            "key": "att-0004-road-pdf",
            "ticket_id": "QT2026110000000004",
            "uploader_user_id": users["citizen_local"].id,
            "uploader_role": "citizen",
            "uploader_department_id": None,
            "attachment_type": "citizen_material",
            "visibility": "public",
            "original_filename": "路面破损现场测量说明.pdf",
            "content_type": "application/pdf",
            "payload": road_pdf,
        },
        {
            "key": "att-0008-site-png",
            "ticket_id": "QT2026110000000008",
            "uploader_user_id": users["citizen_local"].id,
            "uploader_role": "citizen",
            "uploader_department_id": None,
            "attachment_type": "site_photo",
            "visibility": "public",
            "original_filename": "滨河小区垃圾转运点现场照片.png",
            "content_type": "image/png",
            "payload": site_png,
        },
        {
            "key": "att-0010-official-pdf",
            "ticket_id": "QT2026110000000010",
            "uploader_user_id": users["department_local"].id,
            "uploader_role": "department_staff",
            "uploader_department_id": department_ids["general-intake"],
            "attachment_type": "official_document",
            "visibility": "public",
            "original_filename": "学府巷楼道供电抢修验收确认单.pdf",
            "content_type": "application/pdf",
            "payload": power_pdf,
        },
    ]

    persisted = 0
    for spec in attachment_specs:
        tid = spec["ticket_id"]
        if tid not in tickets_by_id:
            continue
        att_id = _deterministic_uuid4(spec["key"])
        object_key = f"tickets/{tid}/{att_id}"
        payload = spec["payload"]
        size_bytes = len(payload)
        digest = hashlib.sha256(payload).hexdigest()

        # Check object existence idempotently; skip DB insert if storage is unreachable.
        needs_upload = False
        try:
            existing_size = storage.size(object_key)
            if existing_size != size_bytes:
                needs_upload = True
        except AttributeError:
            # In-memory test fakes without .size()
            needs_upload = True
        except Exception as exc:
            code = getattr(exc, "code", None)
            if isinstance(exc, (KeyError, FileNotFoundError)) or (
                S3Error is not None and isinstance(exc, S3Error) and code in {"NoSuchKey", "NoSuchBucket", "NotFound"}
            ):
                needs_upload = True
            else:
                logger.warning("Seed attachment skipped (%s unreachable): %s", object_key, exc)
                continue

        if needs_upload:
            try:
                storage.put(object_key, io.BytesIO(payload), size_bytes, spec["content_type"])
            except Exception as exc:
                logger.warning("Seed attachment upload failed (%s): %s", object_key, exc)
                continue

        existing = db.scalar(
            select(TicketAttachmentModel).where(
                or_(
                    TicketAttachmentModel.id == att_id,
                    TicketAttachmentModel.object_key == object_key,
                )
            )
        )
        if not existing:
            db.add(
                TicketAttachmentModel(
                    id=att_id,
                    ticket_id=tid,
                    uploader_user_id=spec["uploader_user_id"],
                    uploader_role=spec["uploader_role"],
                    uploader_department_id=spec["uploader_department_id"],
                    attachment_type=spec["attachment_type"],
                    visibility=spec["visibility"],
                    original_filename=spec["original_filename"],
                    content_type=spec["content_type"],
                    size_bytes=size_bytes,
                    sha256=digest,
                    storage_provider="s3",
                    storage_bucket=storage.bucket,
                    object_key=object_key,
                    scan_status="clean",
                    scan_engine="seed-verified",
                    scan_detail="seed demo verified clean",
                    scanned_at=now,
                    is_deleted=False,
                    created_at=tickets_by_id[tid].created_at + timedelta(minutes=10),
                )
            )
        else:
            existing.storage_bucket = storage.bucket
            existing.size_bytes = size_bytes
            existing.sha256 = digest
            existing.scan_status = "clean"
            existing.scan_engine = "seed-verified"
            existing.scan_detail = "seed demo verified clean"
            existing.scanned_at = existing.scanned_at or now
            existing.is_deleted = False
        persisted += 1
    db.flush()
    return persisted


def _seed_demo_ai_suggestions(
    db,
    users: dict[str, UserModel],
    department_ids: dict[str, int],
    tickets_by_id: dict[str, TicketModel],
    now: datetime,
) -> int:
    """Seed schema-validated triage_assistant and handling_assistant suggestions (advisory_only=True)."""
    agent_id = users["agent_local"].id
    dept_user_id = users["department_local"].id

    def _triage_payload(ticket: TicketModel, dept_name: str, dept_code: str, category_label: str) -> dict:
        raw = {
            "case_summary": {
                "description": ticket.description,
                "location": ticket.location,
                "duration": ticket.occurred_at_text or "近期发生",
                "affected_scope": "周边居民及通行群众",
            },
            "classification": {
                "request_type": ticket.request_type,
                "category": "城市管理",
                "subcategory": category_label,
                "reason": f"诉求明确涉及{category_label}，建议归类至对应末级分类。",
            },
            "urgency": {
                "level": ticket.priority,
                "emergency": ticket.priority in {"urgent", "major"},
                "reason": "结合诉求对公共安全与日常通行的影响程度给出分诊建议。",
            },
            "completeness": {
                "complete": not ticket.needs_supplement,
                "known_fields": ["诉求描述", "具体地点", "发生时间", "联系方式"],
                "missing_fields": [],
                "follow_up_questions": [],
                "completeness_score": 92,
            },
            "department_candidates": [
                {
                    "department_id": department_ids.get(dept_code),
                    "department_name": dept_name,
                    "recommendation_level": "high",
                    "reason": f"历史同类{category_label}工单主要由{dept_name}牵头承办。",
                    "historical_cases": 12,
                    "score": 0.91,
                },
                {
                    "department_id": department_ids.get("general-intake"),
                    "department_name": "综合受理",
                    "recommendation_level": "medium",
                    "reason": "若涉及跨区权属边界，可由综合受理统筹协办。",
                    "historical_cases": 5,
                    "score": 0.56,
                },
            ],
            "sla_recommendation": {
                "response_deadline": "2 小时内完成受理分派",
                "handling_deadline": "24-48 小时内完成现场核查处置",
                "reason": "按市政分类默认 SLA 时限及优先等级建议。",
            },
            "intake_notice_draft": "您的诉求已收悉，我平台将结合核查情况尽快分派相关责任部门处理，结果仅供人工受理参考。",
            "advisory_only": True,
            "capability": "triage_assistant",
            "confidence_labels": {"classification": 91, "department": 89, "urgency": 86},
            "confidence": 89,
        }
        checked = validate_triage_response(raw)
        if not checked.ok or not checked.data:
            raise RuntimeError(f"Seed triage suggestion failed schema check: {checked.detail}")
        return checked.data

    def _handling_payload(ticket: TicketModel, dept_name: str, category_label: str) -> dict:
        raw = {
            "case_summary": {
                "description": ticket.description,
                "assigned_department": dept_name,
                "classification": category_label,
                "known_facts": [ticket.location, ticket.occurred_at_text or "待现场核验"],
            },
            "verification_checklist": [
                "核实市民描述的具体点位与设施权属",
                "查验现场安全隐患并留存处置前影像",
                "核对同类事件历史办结口径与时限要求",
            ],
            "handling_plan": [
                "安排一线核查人员到场踏勘并登记台账",
                "明确主责及协办单位处置时间节点",
                "处置完成后补充前后对比影像再拟定答复",
            ],
            "policy_references": ["《城市公共设施管护与便民热线办理规范》"],
            "risk_warnings": ["临近 SLA 时限请优先核查留痕", "未核验现场前不得做出办结承诺"],
            "missing_handling_facts": ["现场核查实拍记录", "具体修复或协调时间节点"],
            "collaboration_suggestions": ["如遇跨部门权属界面不清，可发起协办核验任务"],
            "evidence_checklist": ["现场位置照", "核查处理台账", "整改前后对比照"],
            "reply_template": "经现场核查，该点位位于【位置】，责任权属为【权属单位】，工作人员于【处理时间】采取【处理措施】，目前【处理状态】。",
            "reply_draft": "经现场核查，该点位位于【位置】，责任权属为【权属单位】，工作人员于【处理时间】采取【处理措施】，目前【处理状态】。",
            "facts_sufficient": False,
            "advisory_only": True,
            "capability": "handling_assistant",
            "confidence": 85,
        }
        checked = validate_handling_response(raw, facts_sufficient=False)
        if not checked.ok or not checked.data:
            raise RuntimeError(f"Seed handling suggestion failed schema check: {checked.detail}")
        return checked.data

    specs = [
        {
            "ticket_id": "QT2026110000000002",
            "suggestion_type": "triage_assistant",
            "risk_level": "attention",
            "confidence": 89,
            "generated_by": agent_id,
            "reviewed_by": None,
            "review_decision": None,
            "review_comment": None,
            "reviewed_at": None,
            "payload": _triage_payload(tickets_by_id["QT2026110000000002"], "城市管理", "urban-management", "路灯故障"),
        },
        {
            "ticket_id": "QT2026110000000004",
            "suggestion_type": "triage_assistant",
            "risk_level": "attention",
            "confidence": 91,
            "generated_by": agent_id,
            "reviewed_by": agent_id,
            "review_decision": "adopted_with_edits",
            "review_comment": "采纳道路养护分派建议，并将优先级由普通上调为加急。",
            "reviewed_at": tickets_by_id["QT2026110000000004"].accepted_at,
            "payload": _triage_payload(tickets_by_id["QT2026110000000004"], "城市管理", "urban-management", "道路破损"),
        },
        {
            "ticket_id": "QT2026110000000007",
            "suggestion_type": "triage_assistant",
            "risk_level": "none",
            "confidence": 88,
            "generated_by": agent_id,
            "reviewed_by": agent_id,
            "review_decision": "helpful",
            "review_comment": "部门推荐和公交接驳要素提取准确。",
            "reviewed_at": tickets_by_id["QT2026110000000007"].accepted_at,
            "payload": _triage_payload(tickets_by_id["QT2026110000000007"], "交通运输", "transport", "公交接驳建议"),
        },
        {
            "ticket_id": "QTDEMO000000000001",
            "suggestion_type": "handling_assistant",
            "risk_level": "none",
            "confidence": 86,
            "generated_by": dept_user_id,
            "reviewed_by": dept_user_id,
            "review_decision": "adopted",
            "review_comment": "已采纳核查清单与便民服务时段答复结构。",
            "reviewed_at": tickets_by_id["QTDEMO000000000001"].accepted_at + timedelta(minutes=30),
            "payload": _handling_payload(tickets_by_id["QTDEMO000000000001"], "综合受理", "社区公共服务咨询"),
        },
        {
            "ticket_id": "QT2026110000000006",
            "suggestion_type": "handling_assistant",
            "risk_level": "attention",
            "confidence": 84,
            "generated_by": dept_user_id,
            "reviewed_by": None,
            "review_decision": None,
            "review_comment": None,
            "reviewed_at": None,
            "payload": _handling_payload(tickets_by_id["QT2026110000000006"], "综合受理", "供水停水"),
        },
        {
            "ticket_id": "QT2026110000000008",
            "suggestion_type": "handling_assistant",
            "risk_level": "urgent",
            "confidence": 82,
            "generated_by": dept_user_id,
            "reviewed_by": dept_user_id,
            "review_decision": "rejected",
            "review_comment": "现场渗滤液溢流需立即启动跨部门联合清运，已采用升级应急处置流程。",
            "reviewed_at": tickets_by_id["QT2026110000000008"].accepted_at + timedelta(hours=2),
            "payload": _handling_payload(tickets_by_id["QT2026110000000008"], "城市管理", "垃圾清运"),
        },
    ]

    for spec in specs:
        tid = spec["ticket_id"]
        stype = spec["suggestion_type"]
        sug_id = _deterministic_uuid4(f"ai:{tid}:{stype}")
        fingerprint = hashlib.sha256(f"seed-ai:{tid}:{stype}:v1".encode("utf-8")).hexdigest()
        existing = db.scalar(
            select(AiSuggestionModel).where(
                or_(
                    AiSuggestionModel.id == sug_id,
                    (AiSuggestionModel.ticket_id == tid)
                    & (AiSuggestionModel.suggestion_type == stype)
                    & (AiSuggestionModel.input_fingerprint == fingerprint),
                )
            )
        )
        if not existing:
            db.add(
                AiSuggestionModel(
                    id=sug_id,
                    ticket_id=tid,
                    suggestion_type=stype,
                    status="completed",
                    risk_level=spec["risk_level"],
                    confidence=spec["confidence"],
                    provider="rules",
                    model_name="phase6-rules-v1",
                    input_fingerprint=fingerprint,
                    result_json=json.dumps(spec["payload"], ensure_ascii=False),
                    explanation=f"由演示规则引擎预置（capability={stype}，advisory_only=true），仅供人工参考。",
                    generated_by_user_id=spec["generated_by"],
                    reviewed_by_user_id=spec["reviewed_by"],
                    review_decision=spec["review_decision"],
                    review_comment=spec["review_comment"],
                    reviewed_at=spec["reviewed_at"],
                    created_at=tickets_by_id[tid].created_at + timedelta(minutes=15),
                )
            )
    db.flush()
    return len(specs)


def _seed_demo_aftercare(
    db,
    users: dict[str, UserModel],
    tickets_by_id: dict[str, TicketModel],
    now: datetime,
) -> dict[str, int]:
    """Seed feedbacks, follow-up tasks, phone follow-up records, and appeals idempotently."""
    citizen_id = users["citizen_local"].id
    agent_id = users["agent_local"].id
    admin_id = users["admin_local"].id

    # 1. Ticket feedbacks
    feedback_specs = [
        (
            "QT2026110000000014",
            1,
            "dissatisfied",
            "dissatisfied_recorded",
            "垃圾清运频次仍偏低，晚间助餐点周边仍有异味，希望进一步整改。",
            tickets_by_id["QT2026110000000014"].resolved_at + timedelta(hours=10),
        ),
        (
            "QT2026110000000015",
            1,
            "satisfied",
            "closed",
            "青云路路灯当晚即恢复亮灯，抢修响应迅速。",
            tickets_by_id["QT2026110000000015"].closed_at,
        ),
        (
            "QT2026110000000017",
            2,
            "mostly_satisfied",
            "closed",
            "二次整改后社区无障碍坡道坡度合理、防滑效果好。",
            tickets_by_id["QT2026110000000017"].closed_at,
        ),
    ]
    for tid, res_ver, rating, result, comment, ts in feedback_specs:
        stmt = pg_insert(TicketFeedbackModel).values(
            ticket_id=tid,
            citizen_user_id=citizen_id,
            resolution_version=res_ver,
            rating=rating,
            comment=comment,
            result=result,
            created_at=ts,
        ).on_conflict_do_nothing(index_elements=["ticket_id", "resolution_version"])
        db.execute(stmt)

    # 2. Follow-up tasks
    followup_specs = [
        {
            "ticket_id": "QT2026110000000013",
            "handling_round": 1,
            "status": "pending",
            "assigned_user_id": agent_id,
            "due_at": now + timedelta(hours=24),
            "completed_at": None,
            "created_at": tickets_by_id["QT2026110000000013"].resolved_at,
        },
        {
            "ticket_id": "QT2026110000000014",
            "handling_round": 1,
            "status": "in_progress",
            "assigned_user_id": agent_id,
            "due_at": now + timedelta(hours=12),
            "completed_at": None,
            "created_at": tickets_by_id["QT2026110000000014"].resolved_at,
        },
        {
            "ticket_id": "QT2026110000000015",
            "handling_round": 1,
            "status": "cancelled",
            "assigned_user_id": agent_id,
            "due_at": tickets_by_id["QT2026110000000015"].resolved_at + timedelta(hours=48),
            "completed_at": tickets_by_id["QT2026110000000015"].closed_at,
            "created_at": tickets_by_id["QT2026110000000015"].resolved_at,
        },
        {
            "ticket_id": "QT2026110000000016",
            "handling_round": 1,
            "status": "completed",
            "assigned_user_id": agent_id,
            "due_at": tickets_by_id["QT2026110000000016"].resolved_at + timedelta(hours=48),
            "completed_at": tickets_by_id["QT2026110000000016"].closed_at,
            "created_at": tickets_by_id["QT2026110000000016"].resolved_at,
        },
    ]
    task_ids_by_ticket: dict[str, str] = {}
    for spec in followup_specs:
        tid = spec["ticket_id"]
        h_round = spec["handling_round"]
        task_id = _deterministic_uuid4(f"followup:{tid}:r{h_round}")
        existing_task = db.scalar(
            select(FollowUpTaskModel).where(
                FollowUpTaskModel.ticket_id == tid,
                FollowUpTaskModel.handling_round == h_round,
            )
        )
        if not existing_task:
            existing_task = FollowUpTaskModel(
                id=task_id,
                ticket_id=tid,
                handling_round=h_round,
                status=spec["status"],
                assigned_user_id=spec["assigned_user_id"],
                due_at=spec["due_at"],
                completed_at=spec["completed_at"],
                created_at=spec["created_at"],
            )
            db.add(existing_task)
            db.flush()
        task_ids_by_ticket[tid] = existing_task.id

    # 3. Phone follow-up records
    call_specs = [
        {
            "key": "call-14-1",
            "ticket_id": "QT2026110000000014",
            "contact_result": "no_answer",
            "satisfaction": None,
            "outcome": "needs_followup",
            "notes": "首次电话回访无人接听，已登记次日工作时段再次致电跟进。",
            "created_at": tickets_by_id["QT2026110000000014"].resolved_at + timedelta(hours=16),
        },
        {
            "key": "call-16-1",
            "ticket_id": "QT2026110000000016",
            "contact_result": "reached",
            "satisfaction": "satisfied",
            "outcome": "confirmed",
            "notes": "电话回访来电人对公交候车亭顶棚及盲道修缮结果表示满意，确认办结。",
            "created_at": tickets_by_id["QT2026110000000016"].closed_at,
        },
    ]
    for spec in call_specs:
        tid = spec["ticket_id"]
        rec_id = _deterministic_uuid4(spec["key"])
        if not db.get(PhoneFollowUpRecordModel, rec_id):
            db.add(
                PhoneFollowUpRecordModel(
                    id=rec_id,
                    task_id=task_ids_by_ticket[tid],
                    ticket_id=tid,
                    caller_user_id=agent_id,
                    contact_result=spec["contact_result"],
                    satisfaction=spec["satisfaction"],
                    outcome=spec["outcome"],
                    notes=spec["notes"],
                    created_at=spec["created_at"],
                )
            )

    # 4. Appeals (submitted / reprocessing / completed / rejected)
    appeal_specs = [
        {
            "ticket_id": "QT2026110000000014",
            "sequence": 1,
            "appeal_no": "QT2026110000000014-SS-1",
            "status": "submitted",
            "reason": "助餐点垃圾桶虽已挪位，但晚间高峰仍存在清运滞后与异味问题。",
            "desired_resolution": "希望增加每日晚间 20:30 固定清运班次并公示负责人。",
            "review_comment": None,
            "reviewed_by_user_id": None,
            "reviewed_at": None,
            "reprocess_instructions": None,
            "result_summary": None,
            "completed_at": None,
            "created_at": tickets_by_id["QT2026110000000014"].resolved_at + timedelta(hours=12),
        },
        {
            "ticket_id": "QT2026110000000012",
            "sequence": 1,
            "appeal_no": "QT2026110000000012-SS-1",
            "status": "reprocessing",
            "reason": "北门东侧转角灌木仍高于 1.2 米，早高峰接送学生存在视野遮挡。",
            "desired_resolution": "请补充对东侧转角灌木做低矮化修剪并联合复核。",
            "review_comment": "申诉情况属实，同意进入第 2 轮重新办理并加派综合受理复核。",
            "reviewed_by_user_id": admin_id,
            "reviewed_at": now - timedelta(days=1),
            "reprocess_instructions": "请教育部门会同园林养护完成转角灌木降高修剪，由综合受理复核现场视野。",
            "result_summary": None,
            "completed_at": None,
            "created_at": tickets_by_id["QT2026110000000012"].created_at + timedelta(days=3),
        },
        {
            "ticket_id": "QT2026110000000017",
            "sequence": 1,
            "appeal_no": "QT2026110000000017-SS-1",
            "status": "completed",
            "reason": "原坡道坡度过陡且雨天易打滑，老年人轮椅通行困难。",
            "desired_resolution": "要求按无障碍设计标准放缓坡度并增设防滑条和扶手。",
            "review_comment": "同意复核并重新派发社区民政二次整改。",
            "reviewed_by_user_id": admin_id,
            "reviewed_at": tickets_by_id["QT2026110000000017"].created_at + timedelta(hours=26),
            "reprocess_instructions": "按 1:12 坡度标准改造坡道并安装双侧扶手，验收照片归档。",
            "result_summary": "已完成坡道扩坡、防滑条铺设及双侧不锈钢扶手安装，现场复验合格。",
            "completed_at": tickets_by_id["QT2026110000000017"].resolved_at,
            "created_at": tickets_by_id["QT2026110000000017"].created_at + timedelta(hours=24),
        },
        {
            "ticket_id": "QT2026110000000015",
            "sequence": 1,
            "appeal_no": "QT2026110000000015-SS-1",
            "status": "rejected",
            "reason": "希望追加安装路灯夜间亮度可调控制模块。",
            "desired_resolution": "建议将普通路段路灯全线升级为智能调光灯头。",
            "review_comment": "经复核本工单报修故障已彻底修复且照度符合现行市政标准，智能升级建议请另行提交。",
            "reviewed_by_user_id": admin_id,
            "reviewed_at": tickets_by_id["QT2026110000000015"].closed_at - timedelta(hours=1),
            "reprocess_instructions": None,
            "result_summary": None,
            "completed_at": tickets_by_id["QT2026110000000015"].closed_at - timedelta(hours=1),
            "created_at": tickets_by_id["QT2026110000000015"].resolved_at + timedelta(hours=2),
        },
    ]
    for spec in appeal_specs:
        tid = spec["ticket_id"]
        seq = spec["sequence"]
        appeal_id = _deterministic_uuid4(f"appeal:{tid}:s{seq}")
        stmt = pg_insert(AppealModel).values(
            id=appeal_id,
            appeal_no=spec["appeal_no"],
            ticket_id=tid,
            citizen_user_id=citizen_id,
            sequence=seq,
            status=spec["status"],
            reason=spec["reason"],
            desired_resolution=spec["desired_resolution"],
            review_comment=spec["review_comment"],
            reviewed_by_user_id=spec["reviewed_by_user_id"],
            reviewed_at=spec["reviewed_at"],
            reprocess_instructions=spec["reprocess_instructions"],
            result_summary=spec["result_summary"],
            completed_at=spec["completed_at"],
            created_at=spec["created_at"],
        ).on_conflict_do_nothing(index_elements=["ticket_id", "sequence"])
        db.execute(stmt)
    db.flush()
    return {"follow_up_tasks": len(followup_specs), "appeals": len(appeal_specs)}


def _seed_demo_notifications(
    db,
    users: dict[str, UserModel],
    tickets_by_id: dict[str, TicketModel],
    now: datetime,
) -> int:
    """Seed unread and read notifications across all 4 demo roles idempotently."""
    specs = [
        # citizen_local
        ("citizen_local", "QT2026110000000003", "supplement_required", "unread", "需要补充材料",
         "工单 QT2026110000000003 需要补充材料：请补充具体路口方位参照物及井盖编号。", None, now - timedelta(minutes=50)),
        ("citizen_local", "QT2026110000000013", "awaiting_confirmation", "unread", "等待市民确认",
         "请查看工单 QT2026110000000013 的办理结果并确认或提出申诉。", None, now - timedelta(hours=6)),
        ("citizen_local", "QT2026110000000015", "ticket_closed", "read", "工单已办结",
         "工单 QT2026110000000015 已办结，感谢您的参与。", now - timedelta(days=2), now - timedelta(days=10)),
        # agent_local
        ("agent_local", "QT2026110000000003", "ticket_due_soon", "unread", "工单即将超时",
         "工单 QT2026110000000003 临近当前受理时限，请及时跟进。", None, now - timedelta(minutes=30)),
        ("agent_local", "QT2026110000000002", "ticket_created", "unread", "工单创建成功",
         "市民新提交诉求，工单号为 QT2026110000000002，请尽快核验受理。", None, now - timedelta(minutes=20)),
        ("agent_local", "QT2026110000000004", "ticket_accepted", "read", "工单已受理",
         "工单 QT2026110000000004 已受理，正在安排派发承办。", now - timedelta(hours=12), now - timedelta(days=1)),
        # department_local
        ("department_local", "QT2026110000000006", "ticket_assigned", "unread", "工单已派发",
         "工单 QT2026110000000006 已派发至综合受理部门，请及时签收办理。", None, now - timedelta(hours=16)),
        ("department_local", "QT2026110000000010", "ticket_due_soon", "unread", "工单即将超时",
         "工单 QT2026110000000010 临近办理时限，请关注复核进度。", None, now - timedelta(minutes=45)),
        ("department_local", "QT2026110000000008", "ticket_overdue", "unread", "工单已超时",
         "工单 QT2026110000000008 协办任务已超过办理时限，请立即处理。", None, now - timedelta(hours=4)),
        ("department_local", "QT2026110000000012", "appeal_approved", "read", "申诉审核通过",
         "工单 QT2026110000000012 的申诉已通过审核，已加派复核协办任务。", now - timedelta(hours=10), now - timedelta(hours=18)),
        # admin_local
        ("admin_local", "QT2026110000000008", "ticket_overdue", "unread", "工单已超时",
         "工单 QT2026110000000008 已超过办理时限，请立即督办。", None, now - timedelta(hours=5)),
        ("admin_local", "QT2026110000000014", "appeal_submitted", "unread", "收到市民申诉",
         "工单 QT2026110000000014 有新的市民申诉，请审核处理。", None, now - timedelta(hours=8)),
        ("admin_local", "QT2026110000000017", "appeal_completed", "read", "申诉处理完成",
         "工单 QT2026110000000017 的重新办理结果已出具并归档。", now - timedelta(days=3), now - timedelta(days=11)),
    ]

    for username, tid, event_type, status, title, content, read_at, created_at in specs:
        if tid not in tickets_by_id:
            continue
        user_id = users[username].id
        event_key = f"seed:{event_type}:{tid}:{username}:{status}"
        notif_id = _deterministic_uuid4(f"notif:{event_key}")
        stmt = pg_insert(NotificationModel).values(
            id=notif_id,
            recipient_user_id=user_id,
            ticket_id=tid,
            event_type=event_type,
            channel="in_app",
            title=title,
            content=content,
            status=status,
            delivery_status="delivered",
            event_key=event_key,
            metadata_json=json.dumps({"ticket_id": tid, "seed": True}, ensure_ascii=False),
            read_at=read_at,
            created_at=created_at,
        ).on_conflict_do_nothing(index_elements=["event_key"])
        db.execute(stmt)
    db.flush()
    return len(specs)


def _seed_demo_audit_logs(
    db,
    users: dict[str, UserModel],
    tickets_by_id: dict[str, TicketModel],
    now: datetime,
) -> int:
    """Seed deterministic, idempotent audit logs across key lifecycle actions."""
    citizen_id = users["citizen_local"].id
    agent_id = users["agent_local"].id
    dept_user_id = users["department_local"].id
    admin_id = users["admin_local"].id

    existing_rids = set(
        db.scalars(
            select(AuditLogModel.request_id).where(AuditLogModel.request_id.like("seed-audit-%"))
        ).all()
    )
    has_legacy_seed_demo = db.scalar(
        select(AuditLogModel.id)
        .where(
            AuditLogModel.action == "seed_demo",
            AuditLogModel.resource_id == "QTDEMO000000000001",
            AuditLogModel.request_id == "seed-command",
        )
        .limit(1)
    )

    entries = [
        ("seed-audit-0001-demo", admin_id, "seed_demo", "ticket", "QTDEMO000000000001",
         '{"profile":"demo"}', tickets_by_id["QTDEMO000000000001"].created_at),
        ("seed-audit-0002-create", citizen_id, "create_ticket", "ticket", "QT2026110000000002",
         '{"request_type":"投诉"}', tickets_by_id["QT2026110000000002"].created_at),
        ("seed-audit-0004-accept", agent_id, "accept_ticket", "ticket", "QT2026110000000004",
         '{"priority":"expedited"}', tickets_by_id["QT2026110000000004"].accepted_at),
        ("seed-audit-0004-attach", citizen_id, "upload_attachment", "attachment", "QT2026110000000004",
         '{"content_type":"application/pdf","scan_status":"clean"}', tickets_by_id["QT2026110000000004"].created_at + timedelta(minutes=10)),
        ("seed-audit-0004-ai", agent_id, "review_ai_suggestion_adoption", "ai_suggestion", "QT2026110000000004",
         '{"decision":"adopted_with_edits","advisory_only":true}', tickets_by_id["QT2026110000000004"].accepted_at),
        ("seed-audit-0006-assign", agent_id, "assign_ticket", "ticket", "QT2026110000000006",
         '{"department":"general-intake"}', tickets_by_id["QT2026110000000006"].accepted_at + timedelta(minutes=15)),
        ("seed-audit-0010-review", dept_user_id, "submit_for_review", "ticket", "QT2026110000000010",
         '{"collaboration_status":"awaiting_review"}', now - timedelta(hours=4)),
        ("seed-audit-0011-pause", agent_id, "pause_ticket_sla", "ticket", "QT2026110000000011",
         '{"reason":"等待停电窗口"}', now - timedelta(hours=2)),
        ("seed-audit-0012-appeal", admin_id, "review_appeal", "appeal", "QT2026110000000012-SS-1",
         '{"decision":"approved","handling_round":2}', now - timedelta(days=1)),
        ("seed-audit-0013-resolve", agent_id, "review_and_resolve", "ticket", "QT2026110000000013",
         '{"outcome":"resolved"}', tickets_by_id["QT2026110000000013"].resolved_at),
        ("seed-audit-0016-call", agent_id, "record_phone_follow_up", "ticket", "QT2026110000000016",
         '{"contact_result":"reached","outcome":"confirmed"}', tickets_by_id["QT2026110000000016"].closed_at),
        ("seed-audit-0018-reject", agent_id, "reject_ticket", "ticket", "QT2026110000000018",
         '{"rejection_reason_code":"out_of_jurisdiction"}', tickets_by_id["QT2026110000000018"].created_at + timedelta(minutes=35)),
    ]

    inserted = 0
    for rid, actor_id, action, rtype, r_id, details, ts in entries:
        if rid == "seed-audit-0001-demo" and has_legacy_seed_demo:
            continue
        if rid in existing_rids:
            continue
        db.add(
            AuditLogModel(
                actor_user_id=actor_id,
                actor_type="user",
                action=action,
                resource_type=rtype,
                resource_id=r_id,
                outcome="success",
                details=details,
                request_id=rid,
                created_at=ts,
            )
        )
        inserted += 1
    db.flush()
    return inserted


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
    from scripts.rag_evaluate import load_golden

    return count + load_golden(db, kb_doc_ids_by_key)


if __name__ == "__main__":
    result = seed()
    print("Seed 完成：" + "，".join(f"{key}={value}" for key, value in result.items()))
