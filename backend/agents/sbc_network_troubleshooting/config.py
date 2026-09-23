from __future__ import annotations

from backend.agents.sbc_network_troubleshooting.skill_tree_loader import (
    load_skill_tree,
)
from backend.agents.sbc_network_troubleshooting.tree_schema import (
    FaultTreeDefinition,
)


DOMAIN_TOOL_DESCRIPTIONS = {
    "keep_alive_query": "识别中断异常、异常时段和影响对象。",
    "connectionless_continuity_query": "用户确认保活中断后查询无连接连续性；仅合并起止时间均一致的中断，按规划邻居优先给出排查顺序，不合并相互包含的长短中断。",
    "topology_query": "查询指定时间窗和对象间的实时拓扑与落地路径；E1基于选中落地目标及最近一次星上路由快照判断实际落地路由树叶节点。",
    "packetin_query": "核对中断或恢复时刻与 PacketIn 事件是否对应。",
    "landing_table_query": "查询落地卫星表各次上注尝试与直连星收到即扩散的配对观测，按update_id和attempt_no关联并汇总重发次数；没有响应不能单独确定根因，也不证明全网已扩散。",
    "feeder_link_query": "查询馈电链路连续性和落地卫星可用性。",
    "SBC_telemetry_query": "查询SBC仿真数据库中明确参数名对应的设备遥测状态；不同于通用遥测查询技能。",
    "route_table_query": "查询每星每半小时采样的星上路由表快照，可筛选目的星；observation_bdt选择该时刻之前最新快照并返回样本年龄，不把选站路由当星上转发表。",
    "route_path_diagnosis": "选择目标星或其实时邻居的一条实际落地路线，使用同一时刻的星上路由快照逐跳核对目的条目、可达性和下一跳。",
    "laser_link_query": "查询激光链路锁定、上下线和质量状态。",
    "packet_capture": "预留LAN/WAN分接口抓包能力；当前无对应仿真数据，调用时明确返回缺证据。",
    "alarm_event_query": "查询平台告警与设备事件时间线。",
}


def load_runtime_tree() -> FaultTreeDefinition:
    return load_skill_tree(known_tools=set(DOMAIN_TOOL_DESCRIPTIONS))
