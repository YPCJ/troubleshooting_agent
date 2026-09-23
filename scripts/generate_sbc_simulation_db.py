#!/usr/bin/env python3
from __future__ import annotations

import argparse
import itertools
import json
import sqlite3
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Iterable
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from sbc_orbit import MODEL_METADATA, STATIONS, generate_passes, verify_passes
from sbc_schedule import SCHEDULE_METADATA, generate_tracking_plan, verify_tracking_plan


START_BDT = datetime(2026, 8, 8, 0, 0, 0)
END_BDT = datetime(2026, 8, 9, 0, 0, 0)
BDT_EPOCH = datetime(2006, 1, 1, 0, 0, 0)
CONSTELLATION = "A星座"
SPLIT_TOPOLOGY_START = datetime(2026, 8, 8, 12, 0, 0)
SPLIT_TOPOLOGY_END = datetime(2026, 8, 8, 15, 0, 0)
ISOLATED_SATELLITE = "A0603"
FAULT1_START = datetime(2026, 8, 8, 17, 20, 0)
FAULT1_END = datetime(2026, 8, 8, 19, 10, 0)
FAULT3_START = datetime(2026, 8, 8, 18, 0, 0)
FAULT3_END = datetime(2026, 8, 8, 20, 0, 0)


@dataclass(frozen=True)
class FaultScenario:
    laser_fault_satellite: str
    route_loss_satellite: str
    feeder_fault_link_id: int
    feeder_fault_link_name: str
    feeder_fault_landing_satellite: str
    feeder_fault_gateway_id: str


FIELD_MAP: dict[str, tuple[str, list[tuple[str, str | None]]]] = {
    "星地拓扑数据": (
        "ground_link_topology",
        [
            ("星地链路名称", "link_name"),
            ("归属规划星座", "planning_constellation"),
            ("所属星座", "constellation"),
            ("圈号", "orbit_number"),
            ("规划起始时间", "planned_start_bdt"),
            ("实际起始时间", "actual_start_bdt"),
            ("规划结束时间", "planned_end_bdt"),
            ("实际结束时间", "actual_end_bdt"),
            ("馈电实时状态", "feeder_realtime_status"),
            ("开始上注状态", "upload_start_status"),
            ("结束上注状态", "upload_end_status"),
            ("源节点名称", "source_node_name"),
            ("源节点端口号", "source_port"),
            ("目的节点名称", "destination_node_name"),
            ("目的节点端口号", "destination_port"),
            ("链路方向", "link_direction"),
            ("总带宽", "total_bandwidth_mbps"),
            ("馈电通断信息", "feeder_connectivity"),
        ],
    ),
    "星间规划拓扑": (
        "planned_topology",
        [
            ("起始时间", "start_bdt"),
            ("结束时间", "end_bdt"),
            ("所属星座", "constellation"),
            ("变更来源", "change_source"),
            ("星间规划拓扑详情信息", "matrix_json"),
        ],
    ),
    "卫星基础信息": (
        "satellite_basic_info",
        [
            ("资源唯一标识", "satellite_id"),
            ("资源名称", "resource_name"),
            ("业务IPV4地址", "business_ipv4"),
            ("业务IPV6地址", "business_ipv6"),
            ("厂商", "manufacturer"),
            ("网络类型", "network_type"),
            ("资源类型", "resource_type"),
            ("星座构型", "constellation_configuration"),
            ("体制类型", "system_type"),
            ("所属节点", "parent_node"),
            ("资源模型版本", "resource_model_version"),
            ("资源状态", "resource_status"),
        ],
    ),
    "协议网关（地面站）基础信息": (
        "protocol_gateway_basic_info",
        [
            ("设备ID", "gateway_id"),
            ("设备型号", "device_model"),
            ("Ipv4管理地址", "management_ipv4"),
            ("Ipv6管理地址", "management_ipv6"),
        ],
    ),
    "星间实时拓扑": (
        "realtime_topology",
        [
            ("起始时间", "start_bdt"),
            ("结束时间", "end_bdt"),
            ("所属星座", "constellation"),
            ("变更来源", "change_source"),
            ("星间实时拓扑详情信息", "matrix_json"),
        ],
    ),
    "保活时间统计": (
        "keepalive_statistics",
        [
            ("卫星标识", "satellite_id"),
            ("保活开始时间", "keepalive_start_bdt"),
            ("保活结束时间", "keepalive_end_bdt"),
        ],
    ),
    "PacketIn消息": (
        "packetin_message",
        [
            ("所属规划星座", "planning_constellation"),
            ("所属协议", "protocol"),
            ("源IP", "source_ip"),
            ("源端口", "source_port"),
            ("目的IP", "destination_ip"),
            ("目的端口", "destination_port"),
            ("报文序号", "message_sequence"),
            ("报文内容", "message_content"),
            ("接收时间", "received_bdt"),
        ],
    ),
    "网络告警信息（全量告警）": (
        "network_alarm",
        [
            ("告警标题", "alarm_title"),
            ("告警级别", "alarm_level"),
            ("告警类型", "alarm_type"),
            ("告警状态", "alarm_status"),
            ("告警发生时间", "occurred_bdt"),
            ("告警对象类型", "object_type"),
            ("告警网元名称", "network_element_name"),
            ("告警网元设备类型", "network_element_device_type"),
            ("告警定位对象名称", "located_object_name"),
            ("告警来源类型", "source_type"),
            ("告警辅助信息", "additional_info"),
            ("告警问题原因描述", "cause_description"),
            ("告警解决时间", "resolved_bdt"),
        ],
    ),
    "无连接服务连续性统计数据": (
        "connectionless_continuity_statistics",
        [
            ("联通拓扑子段名称", "connected_segment_name"),
            ("理论开始时间", "theoretical_start_bdt"),
            ("理论结束时间", "theoretical_end_bdt"),
            ("子段卫星标识", "satellite_id"),
            ("馈电开始时间", "feeder_start_bdt"),
            ("馈电结束时间", "feeder_end_bdt"),
            ("本星理论时长", "local_theoretical_duration_seconds"),
            ("跨星理论时长", "cross_satellite_theoretical_duration_seconds"),
            ("本星实际时长", "local_actual_duration_seconds"),
            ("跨星实际时长", "cross_satellite_actual_duration_seconds"),
            ("中断次数", "interruption_count"),
        ],
    ),
    "测量结果查询接口": (
        "measurement_query",
        [
            ("所属规划星座", "planning_constellation"),
            ("节点类型（协议网关、星载路由器）", "node_type"),
            ("节点ID", "node_id"),
            ("查询类型（SR3、SG2包含的所有接口类型）", "query_type"),
            ("测量结果", None),
            ("接收时间", "received_bdt"),
        ],
    ),
    "报文日志信息查询接口（全量）": (
        "packet_log",
        [
            ("所属规划星座", "planning_constellation"),
            ("所属协议", "protocol"),
            ("源IP", "source_ip"),
            ("源端口", "source_port"),
            ("目的IP", "destination_ip"),
            ("目的端口", "destination_port"),
            ("报文序号", "message_sequence"),
            ("报文内容", "message_content"),
            ("接收时间", "received_bdt"),
        ],
    ),
    "选站路由信息": (
        "station_selection_route",
        [
            ("选站路由开始时间", "route_start_bdt"),
            ("选站路由结束时间", "route_end_bdt"),
            ("星座类型", "constellation_type"),
            ("卫星标识", "satellite_id"),
            ("信关站标识", "gateway_id"),
            ("选站策略", "selection_strategy"),
        ],
    ),
    "星载路由器遥测参数": (
        "router_telemetry",
        [
            ("数据上报时间", "reported_bdt"),
            ("遥测源", "telemetry_source"),
            ("任务标识", "task_id"),
            ("卫星IP", "satellite_ip"),
            ("参数代号", "parameter_code"),
            ("参数名称", "parameter_name"),
            ("源码", "raw_value"),
            ("参数解析值", "parsed_value"),
            ("参数结果", "parameter_result"),
        ],
    ),
    "激光遥测参数": (
        "laser_telemetry",
        [
            ("数据上报时间", "reported_bdt"),
            ("遥测源", "telemetry_source"),
            ("任务标识", "task_id"),
            ("卫星IP", "satellite_ip"),
            ("参数代号", "parameter_code"),
            ("参数名称", "parameter_name"),
            ("源码", "raw_value"),
            ("参数解析值", "parsed_value"),
            ("参数结果", "parameter_result"),
        ],
    ),
    "激光链路通断信息": (
        "laser_link_event",
        [
            ("链路A端卫星名称", "satellite_a_name"),
            ("链路A端卫星标识", "satellite_a_id"),
            ("链路A端激光标识", "laser_a_id"),
            ("链路B端卫星名称", "satellite_b_name"),
            ("链路B端卫星标识", "satellite_b_id"),
            ("链路B端激光标识", "laser_b_id"),
            ("激光链路状态变更时间", "changed_bdt"),
            ("激光链路状态", "link_status"),
            ("激光链路速率", "link_rate_mbps"),
        ],
    ),
    "卫星历史告警信息": (
        "satellite_historical_alarm",
        [
            ("型号代号", "model_code"),
            ("型号名称", "model_name"),
            ("分系统名称", "subsystem_name"),
            ("所属单机", "device_name"),
            ("告警标识id", "alarm_id"),
            ("告警信息", "alarm_message"),
            ("告警级别", "alarm_level"),
            ("发生时间", "occurred_bdt"),
        ],
    ),
    "卫星OM日志": (
        "satellite_om_log",
        [
            ("卫星名称", "satellite_name"),
            ("接收时间", "received_bdt"),
            ("日志内容", "log_content"),
        ],
    ),
    "测量异常告警": (
        "measurement_anomaly_alarm",
        [
            ("时间", "occurred_bdt"),
            ("链路源端", "link_source"),
            ("链路目的端", "link_destination"),
            ("链路时延", "link_delay_ms"),
        ],
    ),
}


OBSERVATION_SCHEMA = (
    """CREATE TABLE landing_table_update_observation (
        observation_id INTEGER PRIMARY KEY,
        update_id TEXT NOT NULL,
        attempt_no INTEGER NOT NULL CHECK (attempt_no >= 1),
        event_type TEXT NOT NULL CHECK (event_type IN ('uplink', 'receipt_diffusion')),
        observed_bdt TEXT NOT NULL,
        landing_satellite_id TEXT NOT NULL REFERENCES satellite_basic_info(satellite_id),
        gateway_id TEXT NOT NULL REFERENCES protocol_gateway_basic_info(gateway_id),
        ground_link_id INTEGER NOT NULL REFERENCES ground_link_topology(ground_link_id),
        tracking_arc_id TEXT NOT NULL REFERENCES ground_link_topology(tracking_arc_id),
        candidate_ids_json TEXT NOT NULL CHECK (json_valid(candidate_ids_json)),
        UNIQUE (update_id, attempt_no, event_type)
    )""",
    """CREATE INDEX idx_landing_update_time
       ON landing_table_update_observation(landing_satellite_id, observed_bdt)""",
    """CREATE INDEX idx_landing_update_arc
       ON landing_table_update_observation(ground_link_id, observed_bdt)""",
    """CREATE TABLE onboard_routing_table_snapshot (
        snapshot_id INTEGER PRIMARY KEY,
        satellite_id TEXT NOT NULL REFERENCES satellite_basic_info(satellite_id),
        queried_bdt TEXT NOT NULL,
        entries_json TEXT NOT NULL CHECK (json_valid(entries_json)),
        UNIQUE (satellite_id, queried_bdt)
    )""",
    """CREATE INDEX idx_onboard_routing_time
       ON onboard_routing_table_snapshot(queried_bdt, satellite_id)""",
)


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE simulation_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    description TEXT NOT NULL
);

CREATE TABLE source_field_mapping (
    source_name TEXT NOT NULL,
    source_table TEXT NOT NULL,
    field_order INTEGER NOT NULL,
    business_field_name TEXT NOT NULL,
    storage_column TEXT,
    modeled INTEGER NOT NULL CHECK (modeled IN (0, 1)),
    note TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (source_name, business_field_name)
);

CREATE TABLE satellite_basic_info (
    satellite_id TEXT PRIMARY KEY,
    resource_name TEXT NOT NULL UNIQUE,
    business_ipv4 TEXT NOT NULL UNIQUE,
    business_ipv6 TEXT NOT NULL UNIQUE,
    manufacturer TEXT NOT NULL,
    network_type TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    constellation_configuration TEXT NOT NULL,
    system_type TEXT NOT NULL,
    parent_node TEXT NOT NULL,
    resource_model_version TEXT NOT NULL,
    resource_status TEXT NOT NULL,
    orbit_plane INTEGER NOT NULL CHECK (orbit_plane BETWEEN 1 AND 6),
    orbit_slot INTEGER NOT NULL CHECK (orbit_slot BETWEEN 1 AND 10),
    is_networking_satellite INTEGER NOT NULL CHECK (is_networking_satellite IN (0, 1)),
    UNIQUE (orbit_plane, orbit_slot)
);

CREATE TABLE protocol_gateway_basic_info (
    gateway_id TEXT PRIMARY KEY,
    device_model TEXT NOT NULL,
    management_ipv4 TEXT NOT NULL UNIQUE,
    management_ipv6 TEXT NOT NULL UNIQUE,
    gateway_name TEXT NOT NULL UNIQUE,
    latitude_deg REAL NOT NULL,
    longitude_deg REAL NOT NULL
);

CREATE TABLE laser_terminal (
    laser_terminal_id TEXT PRIMARY KEY,
    satellite_id TEXT NOT NULL REFERENCES satellite_basic_info(satellite_id),
    logical_direction TEXT NOT NULL CHECK (logical_direction IN ('UP', 'DOWN', 'LEFT', 'RIGHT')),
    terminal_status TEXT NOT NULL CHECK (terminal_status IN ('在用', '空闲')),
    UNIQUE (satellite_id, logical_direction)
);

CREATE TABLE planned_topology (
    topology_id TEXT PRIMARY KEY,
    start_bdt TEXT NOT NULL,
    end_bdt TEXT NOT NULL,
    constellation TEXT NOT NULL,
    change_source TEXT NOT NULL,
    matrix_json TEXT NOT NULL,
    satellite_order_json TEXT NOT NULL
);

CREATE TABLE realtime_topology (
    topology_id TEXT PRIMARY KEY,
    start_bdt TEXT NOT NULL,
    end_bdt TEXT NOT NULL,
    constellation TEXT NOT NULL,
    change_source TEXT NOT NULL,
    matrix_json TEXT NOT NULL,
    satellite_order_json TEXT NOT NULL
);

CREATE TABLE topology_edge (
    topology_kind TEXT NOT NULL CHECK (topology_kind IN ('规划', '实时')),
    topology_id TEXT NOT NULL,
    source_satellite_id TEXT NOT NULL REFERENCES satellite_basic_info(satellite_id),
    source_laser_id TEXT NOT NULL REFERENCES laser_terminal(laser_terminal_id),
    destination_satellite_id TEXT NOT NULL REFERENCES satellite_basic_info(satellite_id),
    destination_laser_id TEXT NOT NULL REFERENCES laser_terminal(laser_terminal_id),
    is_connected INTEGER NOT NULL CHECK (is_connected IN (0, 1)),
    PRIMARY KEY (
        topology_kind,
        topology_id,
        source_satellite_id,
        destination_satellite_id
    )
);

CREATE TABLE ground_link_topology (
    ground_link_id INTEGER PRIMARY KEY,
    link_name TEXT NOT NULL,
    planning_constellation TEXT NOT NULL,
    constellation TEXT NOT NULL,
    orbit_number INTEGER NOT NULL,
    planned_start_bdt TEXT NOT NULL,
    actual_start_bdt TEXT,
    planned_end_bdt TEXT NOT NULL,
    actual_end_bdt TEXT,
    feeder_realtime_status TEXT NOT NULL CHECK (feeder_realtime_status IN ('正常', '中断', '未知')),
    upload_start_status TEXT NOT NULL,
    upload_end_status TEXT NOT NULL,
    source_node_name TEXT NOT NULL,
    source_port TEXT NOT NULL,
    destination_node_name TEXT NOT NULL,
    destination_port TEXT NOT NULL,
    link_direction TEXT NOT NULL,
    total_bandwidth_mbps INTEGER NOT NULL,
    feeder_connectivity TEXT NOT NULL CHECK (feeder_connectivity IN ('连通', '中断')),
    landing_satellite_id TEXT NOT NULL REFERENCES satellite_basic_info(satellite_id),
    gateway_id TEXT NOT NULL REFERENCES protocol_gateway_basic_info(gateway_id),
    tracking_arc_id TEXT NOT NULL UNIQUE,
    peak_bdt TEXT NOT NULL,
    peak_elevation_deg REAL NOT NULL,
    CHECK (planned_start_bdt < planned_end_bdt),
    CHECK (actual_start_bdt < actual_end_bdt)
);

CREATE TABLE keepalive_landing_candidate (
    candidate_id INTEGER PRIMARY KEY,
    source_satellite_id TEXT NOT NULL REFERENCES satellite_basic_info(satellite_id),
    landing_satellite_id TEXT NOT NULL REFERENCES satellite_basic_info(satellite_id),
    gateway_id TEXT NOT NULL REFERENCES protocol_gateway_basic_info(gateway_id),
    qv_address TEXT NOT NULL,
    landing_address TEXT NOT NULL,
    priority INTEGER NOT NULL,
    is_selected INTEGER NOT NULL CHECK (is_selected IN (0, 1)),
    route_path_json TEXT NOT NULL,
    valid_start_bdt TEXT NOT NULL,
    valid_end_bdt TEXT NOT NULL,
    ground_link_id INTEGER NOT NULL REFERENCES ground_link_topology(ground_link_id),
    CHECK (valid_start_bdt < valid_end_bdt),
    UNIQUE (source_satellite_id, landing_satellite_id, gateway_id, valid_start_bdt)
);

CREATE TABLE keepalive_statistics (
    keepalive_id INTEGER PRIMARY KEY,
    satellite_id TEXT NOT NULL REFERENCES satellite_basic_info(satellite_id),
    keepalive_start_bdt TEXT NOT NULL,
    keepalive_end_bdt TEXT NOT NULL,
    selected_candidate_id INTEGER NOT NULL REFERENCES keepalive_landing_candidate(candidate_id)
);

CREATE TABLE packetin_message (
    packetin_id INTEGER PRIMARY KEY,
    planning_constellation TEXT NOT NULL,
    protocol TEXT NOT NULL,
    source_ip TEXT NOT NULL,
    source_port INTEGER NOT NULL,
    destination_ip TEXT NOT NULL,
    destination_port INTEGER NOT NULL,
    message_sequence INTEGER NOT NULL,
    message_content TEXT NOT NULL,
    received_bdt TEXT NOT NULL,
    event_type TEXT NOT NULL,
    affected_link TEXT NOT NULL,
    occurred_bdt TEXT NOT NULL,
    reporting_satellite_id TEXT NOT NULL REFERENCES satellite_basic_info(satellite_id),
    selected_candidate_id INTEGER NOT NULL REFERENCES keepalive_landing_candidate(candidate_id)
);

CREATE TABLE network_alarm (
    alarm_id TEXT PRIMARY KEY,
    alarm_title TEXT NOT NULL,
    alarm_level TEXT NOT NULL CHECK (alarm_level IN ('严重', '一般', '提醒')),
    alarm_type TEXT NOT NULL,
    alarm_status TEXT NOT NULL CHECK (alarm_status IN ('持续中', '已清除')),
    occurred_bdt TEXT NOT NULL,
    object_type TEXT NOT NULL,
    network_element_name TEXT NOT NULL,
    network_element_device_type TEXT NOT NULL,
    located_object_name TEXT NOT NULL,
    source_type TEXT NOT NULL,
    additional_info TEXT NOT NULL,
    cause_description TEXT NOT NULL,
    resolved_bdt TEXT
);

CREATE TABLE connectionless_continuity_statistics (
    continuity_id INTEGER PRIMARY KEY,
    connected_segment_name TEXT NOT NULL,
    theoretical_start_bdt TEXT NOT NULL,
    theoretical_end_bdt TEXT NOT NULL,
    satellite_id TEXT NOT NULL REFERENCES satellite_basic_info(satellite_id),
    feeder_start_bdt TEXT,
    feeder_end_bdt TEXT,
    local_theoretical_duration_seconds REAL NOT NULL,
    cross_satellite_theoretical_duration_seconds REAL NOT NULL,
    local_actual_duration_seconds REAL NOT NULL,
    cross_satellite_actual_duration_seconds REAL NOT NULL,
    interruption_count INTEGER NOT NULL,
    planned_unavailable_duration_seconds REAL NOT NULL,
    actual_unavailable_duration_seconds REAL NOT NULL,
    selected_candidate_id INTEGER REFERENCES keepalive_landing_candidate(candidate_id)
);

CREATE TABLE measurement_query (
    query_id INTEGER PRIMARY KEY,
    planning_constellation TEXT NOT NULL,
    node_type TEXT NOT NULL CHECK (node_type IN ('协议网关', '星载路由器')),
    node_id TEXT NOT NULL,
    query_type TEXT NOT NULL,
    received_bdt TEXT NOT NULL
);

CREATE TABLE packet_log (
    packet_log_id INTEGER PRIMARY KEY,
    planning_constellation TEXT NOT NULL,
    protocol TEXT NOT NULL,
    source_ip TEXT NOT NULL,
    source_port INTEGER NOT NULL,
    destination_ip TEXT NOT NULL,
    destination_port INTEGER NOT NULL,
    message_sequence INTEGER NOT NULL,
    message_content TEXT NOT NULL,
    received_bdt TEXT NOT NULL
);

CREATE TABLE station_selection_route (
    route_id INTEGER PRIMARY KEY,
    route_start_bdt TEXT NOT NULL,
    route_end_bdt TEXT NOT NULL,
    constellation_type TEXT NOT NULL,
    satellite_id TEXT NOT NULL REFERENCES satellite_basic_info(satellite_id),
    gateway_id TEXT NOT NULL REFERENCES protocol_gateway_basic_info(gateway_id),
    selection_strategy TEXT NOT NULL,
    selected_candidate_id INTEGER NOT NULL REFERENCES keepalive_landing_candidate(candidate_id)
);

CREATE TABLE router_telemetry (
    telemetry_id INTEGER PRIMARY KEY,
    reported_bdt TEXT NOT NULL,
    telemetry_source TEXT NOT NULL,
    task_id TEXT NOT NULL,
    satellite_ip TEXT NOT NULL,
    parameter_code TEXT NOT NULL,
    parameter_name TEXT NOT NULL,
    raw_value TEXT NOT NULL,
    parsed_value TEXT NOT NULL,
    parameter_result TEXT NOT NULL CHECK (parameter_result IN ('正常', '异常', '未知'))
);

CREATE TABLE laser_telemetry (
    telemetry_id INTEGER PRIMARY KEY,
    reported_bdt TEXT NOT NULL,
    telemetry_source TEXT NOT NULL,
    task_id TEXT NOT NULL,
    satellite_ip TEXT NOT NULL,
    parameter_code TEXT NOT NULL,
    parameter_name TEXT NOT NULL,
    raw_value TEXT NOT NULL,
    parsed_value TEXT NOT NULL,
    parameter_result TEXT NOT NULL CHECK (parameter_result IN ('正常', '异常', '未知')),
    laser_terminal_id TEXT NOT NULL REFERENCES laser_terminal(laser_terminal_id)
);

CREATE TABLE laser_link_event (
    event_id INTEGER PRIMARY KEY,
    satellite_a_name TEXT NOT NULL,
    satellite_a_id TEXT NOT NULL REFERENCES satellite_basic_info(satellite_id),
    laser_a_id TEXT NOT NULL REFERENCES laser_terminal(laser_terminal_id),
    satellite_b_name TEXT NOT NULL,
    satellite_b_id TEXT NOT NULL REFERENCES satellite_basic_info(satellite_id),
    laser_b_id TEXT NOT NULL REFERENCES laser_terminal(laser_terminal_id),
    changed_bdt TEXT NOT NULL,
    link_status TEXT NOT NULL CHECK (link_status IN ('连通', '中断')),
    link_rate_mbps INTEGER NOT NULL
);

CREATE TABLE satellite_historical_alarm (
    alarm_id TEXT PRIMARY KEY,
    model_code TEXT NOT NULL,
    model_name TEXT NOT NULL,
    subsystem_name TEXT NOT NULL,
    device_name TEXT NOT NULL,
    alarm_message TEXT NOT NULL,
    alarm_level TEXT NOT NULL CHECK (alarm_level IN ('严重', '一般', '提醒')),
    occurred_bdt TEXT NOT NULL,
    satellite_id TEXT NOT NULL REFERENCES satellite_basic_info(satellite_id)
);

CREATE TABLE satellite_om_log (
    log_id INTEGER PRIMARY KEY,
    satellite_name TEXT NOT NULL,
    received_bdt TEXT NOT NULL,
    log_content TEXT NOT NULL,
    satellite_id TEXT NOT NULL REFERENCES satellite_basic_info(satellite_id)
);

CREATE TABLE measurement_anomaly_alarm (
    anomaly_id INTEGER PRIMARY KEY,
    occurred_bdt TEXT NOT NULL,
    link_source TEXT NOT NULL,
    link_destination TEXT NOT NULL,
    link_delay_ms REAL NOT NULL
);

CREATE TABLE simulation_fault (
    fault_id TEXT PRIMARY KEY,
    fault_type TEXT NOT NULL,
    affected_object TEXT NOT NULL,
    fault_start_bdt TEXT NOT NULL,
    physical_recovery_bdt TEXT NOT NULL,
    service_recovery_bdt TEXT NOT NULL,
    root_cause TEXT NOT NULL,
    description TEXT NOT NULL
);

CREATE TABLE simulation_fault_evidence (
    fault_id TEXT NOT NULL REFERENCES simulation_fault(fault_id),
    evidence_table TEXT NOT NULL,
    evidence_key TEXT NOT NULL,
    evidence_summary TEXT NOT NULL,
    PRIMARY KEY (fault_id, evidence_table, evidence_key)
);

CREATE INDEX idx_keepalive_satellite_time
ON keepalive_statistics (satellite_id, keepalive_start_bdt, keepalive_end_bdt);
CREATE INDEX idx_realtime_topology_time
ON realtime_topology (start_bdt, end_bdt);
CREATE INDEX idx_packetin_time ON packetin_message (received_bdt);
CREATE INDEX idx_network_alarm_time ON network_alarm (occurred_bdt, resolved_bdt);
CREATE INDEX idx_router_telemetry_time ON router_telemetry (reported_bdt, satellite_ip);
CREATE INDEX idx_laser_telemetry_time ON laser_telemetry (reported_bdt, laser_terminal_id);
CREATE INDEX idx_laser_event_time ON laser_link_event (changed_bdt);
CREATE INDEX idx_candidate_satellite_time
ON keepalive_landing_candidate(source_satellite_id, is_selected, valid_start_bdt, valid_end_bdt);

CREATE VIEW v_selected_keepalive_landing AS
SELECT
    c.source_satellite_id,
    c.landing_satellite_id AS networking_satellite_id,
    c.gateway_id,
    c.priority,
    c.route_path_json,
    c.valid_start_bdt,
    c.valid_end_bdt,
    g.link_name AS feeder_link_name,
    g.feeder_realtime_status,
    g.feeder_connectivity
FROM keepalive_landing_candidate AS c
JOIN ground_link_topology AS g
  ON g.ground_link_id = c.ground_link_id
 AND g.actual_start_bdt <= c.valid_start_bdt
 AND g.actual_end_bdt >= c.valid_end_bdt
WHERE c.is_selected = 1;

CREATE VIEW v_keepalive_interruptions AS
WITH intervals AS (
    SELECT satellite_id, keepalive_start_bdt, keepalive_end_bdt
    FROM keepalive_statistics
    UNION ALL
    SELECT satellite_id, (SELECT value FROM simulation_metadata WHERE key = 'start_bdt'),
           (SELECT value FROM simulation_metadata WHERE key = 'start_bdt')
    FROM satellite_basic_info
    UNION ALL
    SELECT satellite_id, (SELECT value FROM simulation_metadata WHERE key = 'end_bdt'),
           (SELECT value FROM simulation_metadata WHERE key = 'end_bdt')
    FROM satellite_basic_info
), ordered AS (
    SELECT
        satellite_id,
        keepalive_end_bdt AS interruption_start_bdt,
        LEAD(keepalive_start_bdt) OVER (
            PARTITION BY satellite_id ORDER BY keepalive_start_bdt, keepalive_end_bdt
        ) AS interruption_end_bdt
    FROM intervals
)
SELECT
    satellite_id,
    interruption_start_bdt,
    interruption_end_bdt,
    ROUND(
        (julianday(interruption_end_bdt) - julianday(interruption_start_bdt)) * 86400, 3
    ) AS interruption_seconds
FROM ordered
WHERE interruption_end_bdt > interruption_start_bdt;

CREATE VIEW v_topology_neighbors AS
SELECT
    r.topology_id,
    r.start_bdt,
    r.end_bdt,
    e.source_satellite_id AS satellite_id,
    e.destination_satellite_id AS neighbor_satellite_id,
    e.is_connected
FROM realtime_topology AS r
JOIN topology_edge AS e
  ON e.topology_kind = '实时' AND e.topology_id = r.topology_id;
"""


SCHEMA += "\n" + ";\n".join(OBSERVATION_SCHEMA) + ";\n"


def bdt(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def bdt_milliseconds(value: datetime) -> int:
    return int((value - BDT_EPOCH).total_seconds() * 1000)


def satellite_id(plane: int, slot: int) -> str:
    return f"A{plane:02d}{slot:02d}"


def satellite_ids() -> list[str]:
    return [satellite_id(plane, slot) for plane in range(1, 7) for slot in range(1, 11)]


def satellite_name(sat_id: str) -> str:
    plane = int(sat_id[1:3])
    slot = int(sat_id[3:5])
    serial = (plane - 1) * 10 + slot
    return f"A星座{serial:04d}星"


def build_edges() -> list[tuple[str, str, str, str]]:
    edges: list[tuple[str, str, str, str]] = []
    for plane in range(1, 7):
        for slot in range(1, 11):
            next_slot = 1 if slot == 10 else slot + 1
            edges.append(
                (
                    satellite_id(plane, slot),
                    f"{satellite_id(plane, slot)}-L-UP",
                    satellite_id(plane, next_slot),
                    f"{satellite_id(plane, next_slot)}-L-DOWN",
                )
            )
    for plane in range(1, 6):
        for slot in range(1, 11):
            edges.append(
                (
                    satellite_id(plane, slot),
                    f"{satellite_id(plane, slot)}-L-RIGHT",
                    satellite_id(plane + 1, slot),
                    f"{satellite_id(plane + 1, slot)}-L-LEFT",
                )
            )
    return edges


def build_directed_arcs(
    edges: Iterable[tuple[str, str, str, str]],
) -> list[tuple[str, str, str, str]]:
    arcs = []
    for satellite_a, laser_a, satellite_b, laser_b in edges:
        arcs.append((satellite_a, laser_a, satellite_b, laser_b))
        arcs.append((satellite_b, laser_b, satellite_a, laser_a))
    return arcs


def build_adjacency(
    arcs: Iterable[tuple[str, str, str, str]],
    disconnected: set[tuple[str, str]] | None = None,
) -> dict[str, set[str]]:
    disconnected = disconnected or set()
    adjacency = {sat_id: set() for sat_id in satellite_ids()}
    for source_satellite, _, destination_satellite, _ in arcs:
        if (source_satellite, destination_satellite) in disconnected:
            continue
        adjacency[source_satellite].add(destination_satellite)
    return adjacency


def shortest_path(adjacency: dict[str, set[str]], start: str, end: str) -> list[str]:
    queue = deque([(start, [start])])
    seen = {start}
    while queue:
        node, path = queue.popleft()
        if node == end:
            return path
        for neighbor in sorted(adjacency[node]):
            if neighbor not in seen:
                seen.add(neighbor)
                queue.append((neighbor, [*path, neighbor]))
    raise ValueError(f"No route from {start} to {end}")


def matrix_json(adjacency: dict[str, set[str]]) -> str:
    ids = satellite_ids()
    matrix = [
        [-1 if row == column else int(column in adjacency[row]) for column in ids]
        for row in ids
    ]
    return json.dumps(matrix, ensure_ascii=False, separators=(",", ":"))


def parse_workbook_fields(path: Path) -> dict[str, list[str]]:
    ns = {
        "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    }

    def column_number(reference: str) -> int:
        letters = "".join(character for character in reference if character.isalpha())
        value = 0
        for character in letters:
            value = value * 26 + ord(character.upper()) - 64
        return value

    with ZipFile(path) as archive:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared_strings = [
                "".join(text.text or "" for text in item.iter(f"{{{ns['m']}}}t"))
                for item in root.findall("m:si", ns)
            ]
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {
            item.attrib["Id"]: item.attrib["Target"] for item in relationships
        }
        first_sheet = list(workbook.find("m:sheets", ns))[0]
        relationship_id = first_sheet.attrib[f"{{{ns['r']}}}id"]
        target = targets[relationship_id].lstrip("/")
        if not target.startswith("xl/"):
            target = f"xl/{target}"
        sheet = ET.fromstring(archive.read(target))

        rows: list[tuple[str, str]] = []
        for row in sheet.findall(".//m:sheetData/m:row", ns):
            values: dict[int, str] = {}
            for cell in row.findall("m:c", ns):
                cell_type = cell.attrib.get("t")
                if cell_type == "inlineStr":
                    value = "".join(
                        text.text or "" for text in cell.findall(".//m:t", ns)
                    )
                else:
                    raw_value = cell.find("m:v", ns)
                    value = "" if raw_value is None else raw_value.text or ""
                    if cell_type == "s" and value:
                        value = shared_strings[int(value)]
                values[column_number(cell.attrib["r"])] = value
            rows.append((values.get(1, ""), values.get(2, "")))

    result: dict[str, list[str]] = {}
    current_source = ""
    for source, field in rows[1:]:
        if source:
            current_source = source
            result[current_source] = []
        if current_source and field:
            result[current_source].append(field)
    return result


def validate_workbook(path: Path) -> None:
    actual = parse_workbook_fields(path)
    expected = {
        source: [business_field for business_field, _ in fields]
        for source, (_, fields) in FIELD_MAP.items()
    }
    if actual != expected:
        missing_sources = sorted(set(expected) - set(actual))
        extra_sources = sorted(set(actual) - set(expected))
        mismatched = sorted(
            source
            for source in set(actual) & set(expected)
            if actual[source] != expected[source]
        )
        raise ValueError(
            "Workbook no longer matches the simulation mapping: "
            f"missing_sources={missing_sources}, extra_sources={extra_sources}, "
            f"mismatched_sources={mismatched}"
        )


def insert_metadata(connection: sqlite3.Connection) -> None:
    rows = [
        ("simulation_name", "天基承载网无连接保活仿真", "仿真数据集名称"),
        ("time_scale", "BDT", "所有无时区后缀的时间字段均为北斗时"),
        ("time_format", "YYYY-MM-DD HH:MM:SS.SSS", "BDT文本时间格式"),
        ("window_semantics", "[start, end)", "仿真时间范围左闭右开"),
        ("start_bdt", bdt(START_BDT), "仿真开始时间"),
        ("end_bdt", bdt(END_BDT), "仿真结束时间，不生成该时刻的新事件"),
        ("start_bdt_milliseconds", str(bdt_milliseconds(START_BDT)), "BDT历元起毫秒"),
        ("end_bdt_milliseconds", str(bdt_milliseconds(END_BDT)), "BDT历元起毫秒"),
        ("satellite_count", "60", "6个轨道面，每面10颗卫星"),
        ("laser_terminal_count", "240", "每颗卫星4个激光终端"),
        ("full_topology_link_count", "110", "轨内首尾相接60条，轨间不闭环50条"),
        ("isolated_topology_link_count", "107", "A0603重构时移除该星3条物理链路"),
        ("isolated_satellite", "A0603", "2026-08-08 12:00-15:00 BDT隔离重构的卫星"),
        ("isolation_window_bdt", "2026-08-08 12:00:00.000/2026-08-08 15:00:00.000", "隔离重构时间窗"),
        ("planned_matrix_directionality", "undirected", "规划矩阵必须对称"),
        ("realtime_matrix_directionality", "directed", "实时矩阵允许两个方向状态独立"),
        (
            "planned_topology_patterns",
            "全连接拓扑;A0603隔离重构且其他59星组网",
            "一天内使用的两种规划拓扑模式",
        ),
        (
            "packetin_events",
            "A0603拓扑切换事件+链路状态异常/馈电状态异常/转发路径可达异常事件",
            "拓扑变化与异常现象的PacketIn事件规则",
        ),
        ("matrix_order", "A0101..A0110,A0201..A0210,...,A0601..A0610", "邻接矩阵行列顺序"),
        ("matrix_values", "-1=self,0=disconnected,1=connected", "拓扑矩阵编码"),
        ("duration_unit", "second", "所有时长字段单位"),
        ("delay_unit", "millisecond", "链路时延单位"),
        ("bandwidth_unit", "Mbps", "带宽和链路速率单位"),
        ("alarm_levels", "严重,一般,提醒", "允许的告警级别"),
        ("alarm_statuses", "持续中,已清除", "允许的告警状态"),
        (
            "keepalive_landing_rule",
            "仅考虑有有效馈电的可达星;本星优先;最少跳数;同跳数按落地星ID、站ID排序;存最优两个候选",
            "保活落地仿真规则",
        ),
        (
            "omitted_business_fields",
            "测量结果查询接口.测量结果",
            "按需求暂不仿真的字段",
        ),
    ]
    connection.executemany(
        "INSERT INTO simulation_metadata(key, value, description) VALUES (?, ?, ?)",
        rows + [(key, value, description) for key, (value, description) in MODEL_METADATA.items()] + [
            *((key, value, description) for key, (value, description) in SCHEDULE_METADATA.items()),
            ("ground_capacity_assumption", "one_satellite_per_station_and_one_station_per_satellite",
             "互斥约束:一站同时仅跟踪一星,一星同时仅接入一站;由测控跟踪计划保证"),
            ("handover_assumption", "no_mid_arc_handover;handover_only_at_arc_boundary",
             "一个跟踪弧段内不切站;仅在服务空窗(落地弧段结束)后才允许切换落地星"),
            ("networking_satellite_flag", "feeder_capability",
             "全部60星具备馈电能力;动态组网星身份以有效星地链路区间为准"),
            ("continuity_semantics", "exclusive_local_cross_unavailable",
             "按时间子段记账;本星优先、本星与跨星互斥;计划无覆盖与隔离不是非计划中断"),
            ("isolation_feeder_policy", "intersatellite_only",
             "A0603重构仅切断星间链路;过境时仍允许本星馈电,不能通过它为其他星落地"),
            ("packetin_delivery", "neighbor_report_store_until_reachable",
             "邻星报告A0603物理链路通断;occurred为检测时刻,received为首次可落地时刻"),
            ("laser_model", "ideal_planned_neighbor_links",
             "保留逻辑邻接和规划重构;不模拟激光指向限制、捕获时间、气象或故障"),
            ("fault_dataset_policy", "symptom_only_no_root_cause",
             "故障数据仅保留现象，不在数据库直接写入根因"),
        ],
    )


def insert_field_mapping(connection: sqlite3.Connection) -> None:
    rows = []
    for source, (table, fields) in FIELD_MAP.items():
        for field_order, (business_field, storage_column) in enumerate(fields, 1):
            modeled = int(storage_column is not None)
            note = "" if modeled else "按需求暂不仿真"
            rows.append(
                (
                    source,
                    table,
                    field_order,
                    business_field,
                    storage_column,
                    modeled,
                    note,
                )
            )
    connection.executemany(
        """
        INSERT INTO source_field_mapping(
            source_name, source_table, field_order, business_field_name,
            storage_column, modeled, note
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def insert_resources(connection: sqlite3.Connection) -> None:
    gateways = [
        ("TJS", "GROUND-GW", "172.20.0.11", "fd20::11", "天津地面站"),
        ("GZS", "GROUND-GW", "172.20.0.12", "fd20::12", "广州地面站"),
        ("CDS", "GROUND-GW", "172.20.0.13", "fd20::13", "成都地面站"),
    ]
    connection.executemany(
        """
        INSERT INTO protocol_gateway_basic_info(
            gateway_id, device_model, management_ipv4, management_ipv6, gateway_name,
            latitude_deg, longitude_deg
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [(*row, *STATIONS[row[0]]) for row in gateways],
    )

    satellite_rows = []
    terminal_rows = []
    for plane in range(1, 7):
        for slot in range(1, 11):
            sat_id = satellite_id(plane, slot)
            satellite_rows.append(
                (
                    sat_id,
                    satellite_name(sat_id),
                    f"10.{plane}.{slot}.1",
                    f"fd00:{plane:x}:{slot:x}::1",
                    "厂商甲" if plane % 2 == 1 else "厂商乙",
                    "天基承载网",
                    "星载路由器",
                    "6轨道面×10星近极轨道",
                    "无连接",
                    f"轨道面{plane:02d}",
                    "SIM-1.0",
                    "在轨",
                    plane,
                    slot,
                    1,
                )
            )
            for direction in ("UP", "DOWN", "LEFT", "RIGHT"):
                unused = (plane == 1 and direction == "LEFT") or (
                    plane == 6 and direction == "RIGHT"
                )
                terminal_rows.append(
                    (
                        f"{sat_id}-L-{direction}",
                        sat_id,
                        direction,
                        "空闲" if unused else "在用",
                    )
                )
    connection.executemany(
        """
        INSERT INTO satellite_basic_info(
            satellite_id, resource_name, business_ipv4, business_ipv6, manufacturer,
            network_type, resource_type, constellation_configuration, system_type,
            parent_node, resource_model_version, resource_status, orbit_plane,
            orbit_slot, is_networking_satellite
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        satellite_rows,
    )
    connection.executemany(
        """
        INSERT INTO laser_terminal(
            laser_terminal_id, satellite_id, logical_direction, terminal_status
        ) VALUES (?, ?, ?, ?)
        """,
        terminal_rows,
    )


def insert_topologies(
    connection: sqlite3.Connection,
    arcs: list[tuple[str, str, str, str]],
) -> None:
    ids_json = json.dumps(satellite_ids(), ensure_ascii=False, separators=(",", ":"))
    full_adjacency = build_adjacency(arcs)
    isolation_directions = {
        (source, destination)
        for source, _, destination, _ in arcs
        if ISOLATED_SATELLITE in (source, destination)
    }
    isolated_adjacency = build_adjacency(arcs, isolation_directions)
    planned_rows = [
        (
            "PLAN-FULL-20260808-001",
            START_BDT,
            SPLIT_TOPOLOGY_START,
            "全天全连接规划",
            full_adjacency,
            set(),
        ),
        (
            "PLAN-ISOLATE-20260808-001",
            SPLIT_TOPOLOGY_START,
            SPLIT_TOPOLOGY_END,
            "A0603隔离重构规划",
            isolated_adjacency,
            isolation_directions,
        ),
        (
            "PLAN-FULL-20260808-002",
            SPLIT_TOPOLOGY_END,
            END_BDT,
            "全天全连接规划",
            full_adjacency,
            set(),
        ),
    ]
    connection.executemany(
        """
        INSERT INTO planned_topology(
            topology_id, start_bdt, end_bdt, constellation, change_source,
            matrix_json, satellite_order_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                topology_id,
                bdt(start),
                bdt(end),
                CONSTELLATION,
                change_source,
                matrix_json(adjacency),
                ids_json,
            )
            for topology_id, start, end, change_source, adjacency, _ in planned_rows
        ],
    )
    realtime_rows = [
        (
            "REAL-FULL-20260808-001",
            START_BDT,
            SPLIT_TOPOLOGY_START,
            "星间拓扑状态采集",
            full_adjacency,
            set(),
        ),
        (
            "REAL-ISOLATE-20260808-001",
            SPLIT_TOPOLOGY_START,
            SPLIT_TOPOLOGY_END,
            "星间拓扑状态采集",
            isolated_adjacency,
            isolation_directions,
        ),
        (
            "REAL-FULL-20260808-002",
            SPLIT_TOPOLOGY_END,
            END_BDT,
            "星间拓扑状态采集",
            full_adjacency,
            set(),
        ),
    ]
    connection.executemany(
        """
        INSERT INTO realtime_topology(
            topology_id, start_bdt, end_bdt, constellation, change_source,
            matrix_json, satellite_order_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                topology_id,
                bdt(start),
                bdt(end),
                CONSTELLATION,
                "星间拓扑状态采集",
                matrix_json(adjacency),
                ids_json,
            )
            for topology_id, start, end, change_source, adjacency, _ in realtime_rows
        ],
    )

    edge_rows = []
    for topology_id, _, _, _, _, disconnected in planned_rows:
        edge_rows.extend(
            (
                "规划",
                topology_id,
                source,
                source_laser,
                destination,
                destination_laser,
                int((source, destination) not in disconnected),
            )
            for source, source_laser, destination, destination_laser in arcs
        )
    for topology_id, _, _, _, _, disconnected in realtime_rows:
        edge_rows.extend(
            (
                "实时",
                topology_id,
                source,
                source_laser,
                destination,
                destination_laser,
                int((source, destination) not in disconnected),
            )
            for source, source_laser, destination, destination_laser in arcs
        )
    connection.executemany(
        """
        INSERT INTO topology_edge(
            topology_kind, topology_id, source_satellite_id, source_laser_id,
            destination_satellite_id, destination_laser_id, is_connected
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        edge_rows,
    )


def insert_ground_passes(connection: sqlite3.Connection) -> None:
    gateway_names = {
        row["gateway_id"]: row["gateway_name"]
        for row in connection.execute(
            "SELECT gateway_id, gateway_name FROM protocol_gateway_basic_info"
        )
    }
    passes = generate_passes()
    verify_passes(passes)
    arcs = generate_tracking_plan()
    verify_tracking_plan(arcs)
    ground_links = []
    for window in arcs:
        landing_satellite, gateway_id = window.satellite_id, window.gateway_id
        start, end = time_at_ms(window.start_ms), time_at_ms(window.end_ms)
        ground_links.append(
            (
                f"GL-{window.arc_id}",
                CONSTELLATION,
                CONSTELLATION,
                window.orbit_number,
                start,
                start,
                end,
                end,
                "正常",
                "上注完成",
                "上注完成",
                satellite_name(landing_satellite),
                "FEEDER-01",
                gateway_names[gateway_id],
                f"RF-{landing_satellite}",
                "双向",
                10000,
                "连通",
                landing_satellite,
                gateway_id,
                window.arc_id,
                time_at_ms(window.peak_ms),
                window.peak_elevation_deg,
            )
        )
    connection.executemany(
        """
        INSERT INTO ground_link_topology(
            link_name, planning_constellation, constellation, orbit_number,
            planned_start_bdt, actual_start_bdt, planned_end_bdt, actual_end_bdt,
            feeder_realtime_status, upload_start_status, upload_end_status,
            source_node_name, source_port, destination_node_name, destination_port,
            link_direction, total_bandwidth_mbps, feeder_connectivity,
            landing_satellite_id, gateway_id, tracking_arc_id, peak_bdt, peak_elevation_deg
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ground_links,
    )


def select_fault_scenario(
    connection: sqlite3.Connection,
) -> FaultScenario:
    landing_satellites = {
        row[0] for row in connection.execute("SELECT DISTINCT landing_satellite_id FROM ground_link_topology")
    }
    non_landing = [
        sat for sat in satellite_ids()
        if sat not in landing_satellites and sat != ISOLATED_SATELLITE
    ]
    if len(non_landing) < 2:
        raise ValueError("Need at least two non-landing satellites for fault scenario")
    planned_intervals = derive_service_intervals(connection, actual=False)
    fault1_start_ms = elapsed_ms(bdt(FAULT1_START))
    fault1_end_ms = elapsed_ms(bdt(FAULT1_END))
    fault3_start_ms = elapsed_ms(bdt(FAULT3_START))
    fault3_end_ms = elapsed_ms(bdt(FAULT3_END))

    route_scores: list[tuple[int, str]] = []
    for candidate in non_landing:
        transit_users = set()
        for source_satellite, intervals in planned_intervals.items():
            if source_satellite == candidate:
                continue
            if any(
                interval.end_ms > fault3_start_ms
                and interval.start_ms < fault3_end_ms
                and interval.choices
                and candidate in interval.choices[0].path[1:-1]
                for interval in intervals
            ):
                transit_users.add(source_satellite)
        route_scores.append((len(transit_users), candidate))
    route_scores.sort(reverse=True)
    route_loss_satellite = route_scores[0][1]

    laser_scores = []
    for candidate in non_landing:
        if candidate == route_loss_satellite:
            continue
        overlapping_segments = sum(
            1
            for interval in planned_intervals[candidate]
            if interval.end_ms > fault1_start_ms
            and interval.start_ms < fault1_end_ms
            and interval.choices
        )
        laser_scores.append((overlapping_segments, candidate))
    laser_scores.sort(reverse=True)
    laser_fault_satellite = laser_scores[0][1]

    link_to_sources: dict[int, set[str]] = {}
    for source_satellite, intervals in planned_intervals.items():
        for interval in intervals:
            if not interval.choices:
                continue
            link_id = interval.choices[0].ground_link_id
            link_to_sources.setdefault(link_id, set()).add(source_satellite)
    link_end_ms = {
        row["ground_link_id"]: elapsed_ms(row["actual_end_bdt"])
        for row in connection.execute("SELECT ground_link_id, actual_end_bdt FROM ground_link_topology")
    }
    ranked_links = sorted(
        (
            (len(sources), link_id)
            for link_id, sources in link_to_sources.items()
            if len(sources) >= 2 and link_end_ms[link_id] < 86_400_000
        ),
        reverse=True,
    )
    if not ranked_links:
        raise ValueError("Cannot find a feeder arc affecting multiple satellites")
    feeder_fault_link_id = ranked_links[0][1]
    row = connection.execute(
        """SELECT link_name, landing_satellite_id, gateway_id
           FROM ground_link_topology WHERE ground_link_id=?""",
        (feeder_fault_link_id,),
    ).fetchone()
    if row is None:
        raise ValueError("Selected feeder fault link is missing")
    return FaultScenario(
        laser_fault_satellite=laser_fault_satellite,
        route_loss_satellite=route_loss_satellite,
        feeder_fault_link_id=feeder_fault_link_id,
        feeder_fault_link_name=row["link_name"],
        feeder_fault_landing_satellite=row["landing_satellite_id"],
        feeder_fault_gateway_id=row["gateway_id"],
    )


def reconfigure_realtime_topology_for_faults(
    connection: sqlite3.Connection,
    arcs: list[tuple[str, str, str, str]],
    scenario: FaultScenario,
) -> None:
    ids_json = json.dumps(satellite_ids(), ensure_ascii=False, separators=(",", ":"))
    isolation_directions = {
        (source, destination)
        for source, _, destination, _ in arcs
        if ISOLATED_SATELLITE in (source, destination)
    }
    laser_fault_directions = {
        (source, destination)
        for source, _, destination, _ in arcs
        if scenario.laser_fault_satellite in (source, destination)
    }
    route_loss_directions = {
        (source, destination)
        for source, _, destination, _ in arcs
        if scenario.route_loss_satellite in (source, destination)
    }
    realtime_rows = [
        ("REAL-FULL-20260808-001", START_BDT, SPLIT_TOPOLOGY_START, "星间拓扑状态采集", set()),
        ("REAL-ISOLATE-20260808-001", SPLIT_TOPOLOGY_START, SPLIT_TOPOLOGY_END, "星间拓扑状态采集", isolation_directions),
        ("REAL-FULL-20260808-002", SPLIT_TOPOLOGY_END, FAULT1_START, "星间拓扑状态采集", set()),
        (
            "REAL-FLT-LASER-20260808-001",
            FAULT1_START,
            FAULT3_START,
            "星间拓扑状态采集",
            laser_fault_directions,
        ),
        (
            "REAL-FLT-COUPLED-20260808-001",
            FAULT3_START,
            FAULT1_END,
            "星间拓扑状态采集",
            laser_fault_directions | route_loss_directions,
        ),
        (
            "REAL-FLT-ROUTE-20260808-001",
            FAULT1_END,
            FAULT3_END,
            "星间拓扑状态采集",
            route_loss_directions,
        ),
        ("REAL-FULL-20260808-003", FAULT3_END, END_BDT, "星间拓扑状态采集", set()),
    ]
    connection.execute("DELETE FROM topology_edge WHERE topology_kind='实时'")
    connection.execute("DELETE FROM realtime_topology")
    connection.executemany(
        """
        INSERT INTO realtime_topology(
            topology_id, start_bdt, end_bdt, constellation, change_source,
            matrix_json, satellite_order_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                topology_id,
                bdt(start),
                bdt(end),
                CONSTELLATION,
                "星间拓扑状态采集",
                matrix_json(build_adjacency(arcs, disconnected)),
                ids_json,
            )
            for topology_id, start, end, change_source, disconnected in realtime_rows
        ],
    )
    edge_rows = []
    for topology_id, _, _, _, disconnected in realtime_rows:
        edge_rows.extend(
            (
                "实时",
                topology_id,
                source,
                source_laser,
                destination,
                destination_laser,
                int((source, destination) not in disconnected),
            )
            for source, source_laser, destination, destination_laser in arcs
        )
    connection.executemany(
        """
        INSERT INTO topology_edge(
            topology_kind, topology_id, source_satellite_id, source_laser_id,
            destination_satellite_id, destination_laser_id, is_connected
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        edge_rows,
    )


def apply_faults_to_ground_links(connection: sqlite3.Connection, scenario: FaultScenario) -> None:
    connection.execute(
        """UPDATE ground_link_topology
           SET feeder_realtime_status='中断', feeder_connectivity='中断',
               upload_start_status='上注异常', upload_end_status='上注异常'
           WHERE ground_link_id=?""",
        (scenario.feeder_fault_link_id,),
    )


def inject_fault_scenarios(
    connection: sqlite3.Connection,
    arcs: list[tuple[str, str, str, str]],
) -> FaultScenario:
    scenario = select_fault_scenario(connection)
    reconfigure_realtime_topology_for_faults(connection, arcs, scenario)
    apply_faults_to_ground_links(connection, scenario)
    fault3_start_ms = elapsed_ms(bdt(FAULT3_START))
    fault3_end_ms = elapsed_ms(bdt(FAULT3_END))
    planned_intervals = derive_service_intervals(connection, actual=False)
    blackout_sources = sorted(
        sat
        for sat, intervals in planned_intervals.items()
        if sat != scenario.route_loss_satellite
        and any(
            interval.end_ms > fault3_start_ms
            and interval.start_ms < fault3_end_ms
            and interval.choices
            and scenario.route_loss_satellite in interval.choices[0].path[1:-1]
            for interval in intervals
        )
    )
    connection.executemany(
        "INSERT INTO simulation_metadata(key, value, description) VALUES (?, ?, ?)",
        [
            ("observed_link_state_satellite", scenario.laser_fault_satellite, "观测到链路状态变化的卫星"),
            ("observed_route_unreachable_satellite", scenario.route_loss_satellite, "观测到转发可达性变化的卫星"),
            ("observed_feeder_unavailable_link_id", str(scenario.feeder_fault_link_id), "观测到馈电不可用的星地弧段ID"),
            ("observed_keepalive_blackout_sources", ",".join(blackout_sources), "观测到同时间窗保活缺失的卫星列表"),
        ],
    )
    return scenario


def time_at_ms(milliseconds: int) -> str:
    return bdt(START_BDT + timedelta(milliseconds=milliseconds))


def elapsed_ms(value: str) -> int:
    return round((datetime.fromisoformat(value) - START_BDT).total_seconds() * 1000)


@dataclass(frozen=True)
class LandingChoice:
    ground_link_id: int
    path: tuple[str, ...]


@dataclass
class ServiceInterval:
    start_ms: int
    end_ms: int
    choices: tuple[LandingChoice, ...]


def reachable_paths(adjacency: dict[str, set[str]], source: str) -> dict[str, tuple[str, ...]]:
    paths = {source: (source,)}
    queue = deque([source])
    while queue:
        node = queue.popleft()
        for neighbor in sorted(adjacency[node]):
            if neighbor not in paths:
                paths[neighbor] = (*paths[node], neighbor)
                queue.append(neighbor)
    return paths


def insert_landing_table_updates(connection: sqlite3.Connection) -> None:
    """Retry one content version every three seconds until receipt or arc exit."""
    candidates_by_link: dict[int, list[sqlite3.Row]] = {}
    for candidate in connection.execute(
        "SELECT * FROM keepalive_landing_candidate ORDER BY candidate_id"
    ):
        candidates_by_link.setdefault(candidate["ground_link_id"], []).append(candidate)
    rows = []
    for link in connection.execute("SELECT * FROM ground_link_topology ORDER BY ground_link_id"):
        start = max(0, elapsed_ms(link["planned_start_bdt"]))
        end = min(86_400_000, elapsed_ms(link["planned_end_bdt"]))
        if start >= end:
            continue
        candidates = candidates_by_link.get(link["ground_link_id"], [])
        boundaries = {start}
        for candidate in candidates:
            boundaries.update(
                elapsed_ms(candidate[column])
                for column in ("valid_start_bdt", "valid_end_bdt")
                if start < elapsed_ms(candidate[column]) < end
            )
        previous_ids = None
        version_starts = sorted(boundaries)
        for version_index, update_ms in enumerate(version_starts):
            candidate_ids = [
                row["candidate_id"] for row in candidates
                if elapsed_ms(row["valid_start_bdt"]) <= update_ms
                < elapsed_ms(row["valid_end_bdt"])
            ]
            if candidate_ids == previous_ids:
                continue
            previous_ids = candidate_ids
            update_id = f"LTU-{link['ground_link_id']}-{update_ms:08d}"
            version_end_ms = (
                version_starts[version_index + 1]
                if version_index + 1 < len(version_starts)
                else end
            )
            identity = (
                link["landing_satellite_id"], link["gateway_id"],
                link["ground_link_id"], link["tracking_arc_id"],
                json.dumps(candidate_ids, separators=(",", ":")),
            )
            can_receive = (
                link["feeder_connectivity"] == "连通"
                and link["feeder_realtime_status"] == "正常"
                and link["actual_start_bdt"]
                and link["actual_end_bdt"]
            )
            actual_start_ms = elapsed_ms(link["actual_start_bdt"]) if can_receive else None
            actual_end_ms = elapsed_ms(link["actual_end_bdt"]) if can_receive else None
            attempt_no = 1
            attempt_ms = update_ms
            while attempt_ms < version_end_ms:
                rows.append((update_id, attempt_no, "uplink", time_at_ms(attempt_ms), *identity))
                receipt_ms = attempt_ms + 1000
                if (can_receive and actual_start_ms <= attempt_ms
                        and receipt_ms < min(end, actual_end_ms)):
                    rows.append((
                        update_id, attempt_no, "receipt_diffusion",
                        time_at_ms(receipt_ms), *identity,
                    ))
                    break
                attempt_no += 1
                attempt_ms += 3000
    connection.executemany(
        """INSERT INTO landing_table_update_observation(
            update_id, attempt_no, event_type, observed_bdt, landing_satellite_id, gateway_id,
            ground_link_id, tracking_arc_id, candidate_ids_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""", rows,
    )


def routing_observation_graphs(
    connection: sqlite3.Connection,
) -> Iterable[tuple[str, dict[str, set[str]]]]:
    """Sample planned links and latest physical observations, without future events."""
    ids = satellite_ids()
    plans = connection.execute("SELECT * FROM planned_topology ORDER BY start_bdt").fetchall()
    realtime = connection.execute("SELECT * FROM realtime_topology ORDER BY start_bdt").fetchall()
    edges: dict[tuple[str, str], dict[tuple[str, str], bool]] = {}
    for edge in connection.execute("SELECT * FROM topology_edge"):
        edges.setdefault((edge["topology_kind"], edge["topology_id"]), {})[
            (edge["source_satellite_id"], edge["destination_satellite_id"])
        ] = bool(edge["is_connected"])
    events = connection.execute(
        """SELECT satellite_a_id, satellite_b_id, changed_bdt, link_status
           FROM laser_link_event ORDER BY changed_bdt, event_id"""
    ).fetchall()
    physical = {}
    event_index = 0
    for minute in range(0, 24 * 60, 30):
        query_time = bdt(START_BDT + timedelta(minutes=minute))
        plan = [row for row in plans if row["start_bdt"] <= query_time < row["end_bdt"]]
        live = [row for row in realtime if row["start_bdt"] <= query_time < row["end_bdt"]]
        if len(plan) != 1 or len(live) != 1:
            raise ValueError(f"Expected one planned and realtime topology at {query_time}")
        while event_index < len(events) and events[event_index]["changed_bdt"] <= query_time:
            event = events[event_index]
            physical[(event["satellite_a_id"], event["satellite_b_id"])] = (
                event["link_status"] == "连通"
            )
            event_index += 1
        planned_edges = edges.get(("规划", plan[0]["topology_id"]), {})
        live_edges = edges.get(("实时", live[0]["topology_id"]), {})
        adjacency = {sat: set() for sat in ids}
        for (source, destination), connected in planned_edges.items():
            # Realtime reachability also includes forwarding state. Direct physical
            # link observations take precedence so route loss is not a laser outage.
            if connected and physical.get((source, destination),
                                          live_edges.get((source, destination), False)):
                adjacency[source].add(destination)
        yield query_time, adjacency


def insert_onboard_routing_snapshots(
    connection: sqlite3.Connection, route_loss_satellite: str | None = "A0306",
) -> None:
    ids = satellite_ids()
    rows = []
    for query_time, adjacency in routing_observation_graphs(connection):
        for source in ids:
            paths = reachable_paths(adjacency, source)
            entries = []
            if not (source == route_loss_satellite
                    and bdt(FAULT3_START) <= query_time < bdt(FAULT3_END)):
                for destination in ids:
                    if destination == source:
                        continue
                    path = paths.get(destination)
                    entries.append({
                        "destination_satellite_id": destination,
                        "reachable": path is not None,
                        "hop_count": len(path) - 1 if path else None,
                        "next_hop_satellite_id": path[1] if path else None,
                        "path": list(path) if path else [],
                    })
            rows.append((source, query_time, json.dumps(entries, separators=(",", ":"))))
    connection.executemany(
        """INSERT INTO onboard_routing_table_snapshot(satellite_id, queried_bdt, entries_json)
           VALUES (?, ?, ?)""", rows,
    )


def verify_observation_tables(connection: sqlite3.Connection) -> None:
    snapshots = connection.execute("SELECT * FROM onboard_routing_table_snapshot").fetchall()
    if len(snapshots) != 60 * 48:
        raise AssertionError("Expected 60 satellites x 48 routing observations")
    ids = set(satellite_ids())
    for row in snapshots:
        if elapsed_ms(row["queried_bdt"]) not in range(0, 86_400_000, 1_800_000):
            raise AssertionError("Routing query is not on the half-hour grid")
        entries = json.loads(row["entries_json"])
        if entries and (len(entries) != 59 or {
            entry["destination_satellite_id"] for entry in entries
        } != ids - {row["satellite_id"]}):
            raise AssertionError("Routing destinations must exclude source and cover other satellites")
    observations = connection.execute("SELECT * FROM landing_table_update_observation").fetchall()
    uplinks = {
        (row["update_id"], row["attempt_no"]): row
        for row in observations if row["event_type"] == "uplink"
    }
    for row in observations:
        link = connection.execute(
            "SELECT * FROM ground_link_topology WHERE ground_link_id=?", (row["ground_link_id"],)
        ).fetchone()
        if any(row[key] != link[key] for key in
               ("landing_satellite_id", "gateway_id", "tracking_arc_id")):
            raise AssertionError("Landing observation does not match its feeder arc")
        if row["event_type"] == "receipt_diffusion":
            uplink = uplinks.get((row["update_id"], row["attempt_no"]))
            if uplink is None or uplink["observed_bdt"] >= row["observed_bdt"]:
                raise AssertionError("Receipt must follow its uplink")
            if any(row[key] != uplink[key] for key in
                   ("ground_link_id", "candidate_ids_json")):
                raise AssertionError("Receipt does not refer to the transmitted version")
            if (link["feeder_connectivity"] != "连通"
                    or link["feeder_realtime_status"] != "正常"
                    or not link["actual_start_bdt"] <= row["observed_bdt"] < link["actual_end_bdt"]):
                raise AssertionError("Receipt requires an established direct feeder")
        for candidate_id in json.loads(row["candidate_ids_json"]):
            candidate = connection.execute(
                "SELECT * FROM keepalive_landing_candidate WHERE candidate_id=?", (candidate_id,)
            ).fetchone()
            update_id = row["update_id"]
            uplink_time = min(
                uplink["observed_bdt"] for key, uplink in uplinks.items()
                if key[0] == update_id
            )
            if (candidate is None or candidate["ground_link_id"] != row["ground_link_id"]
                    or not candidate["valid_start_bdt"] <= uplink_time < candidate["valid_end_bdt"]):
                raise AssertionError("Candidate correlation is invalid at uplink time")
    for table in ("landing_table_update_observation", "onboard_routing_table_snapshot"):
        if connection.execute(f"PRAGMA foreign_key_check({table})").fetchall():
            raise AssertionError(f"Foreign key errors in {table}")


def enrich_observation_tables(
    connection: sqlite3.Connection, route_loss_satellite: str | None = "A0306",
) -> None:
    """Add both tables atomically; never mutate or replace existing data."""
    existing = connection.execute(
        """SELECT name FROM sqlite_master WHERE name IN (
           'landing_table_update_observation', 'onboard_routing_table_snapshot')"""
    ).fetchall()
    if existing:
        raise ValueError("Observation tables already exist; refusing to overwrite them")
    previous_factory = connection.row_factory
    connection.row_factory = sqlite3.Row
    connection.execute("SAVEPOINT sbc_observation_enrichment")
    try:
        # executescript would commit a caller's transaction before running DDL.
        for statement in OBSERVATION_SCHEMA:
            connection.execute(statement)
        insert_landing_table_updates(connection)
        insert_onboard_routing_snapshots(connection, route_loss_satellite)
        verify_observation_tables(connection)
    except Exception:
        connection.execute("ROLLBACK TO sbc_observation_enrichment")
        connection.execute("RELEASE sbc_observation_enrichment")
        raise
    else:
        connection.execute("RELEASE sbc_observation_enrichment")
    finally:
        connection.row_factory = previous_factory


def replace_landing_updates_with_retries(connection: sqlite3.Connection) -> None:
    """Transactionally regenerate only landing observations with retry attempts."""
    columns = {
        row[1] for row in connection.execute(
            "PRAGMA table_info(landing_table_update_observation)"
        )
    }
    if not columns:
        raise ValueError("landing_table_update_observation does not exist")
    required = {
        "observation_id", "update_id", "event_type", "observed_bdt",
        "landing_satellite_id", "gateway_id", "ground_link_id",
        "tracking_arc_id", "candidate_ids_json",
    }
    if not required <= columns:
        raise ValueError("Unexpected landing observation schema")
    previous_factory = connection.row_factory
    connection.row_factory = sqlite3.Row
    connection.execute("SAVEPOINT sbc_landing_retry_migration")
    try:
        connection.execute("DROP TABLE landing_table_update_observation")
        for statement in OBSERVATION_SCHEMA[:3]:
            connection.execute(statement)
        insert_landing_table_updates(connection)
        observations = connection.execute(
            "SELECT * FROM landing_table_update_observation"
        ).fetchall()
        if not observations:
            raise AssertionError("Landing retry migration produced no observations")
        receipts = {
            (row["update_id"], row["attempt_no"])
            for row in observations if row["event_type"] == "receipt_diffusion"
        }
        for update_id, attempt_no in receipts:
            if not any(
                row["update_id"] == update_id
                and row["attempt_no"] == attempt_no
                and row["event_type"] == "uplink"
                for row in observations
            ):
                raise AssertionError("Receipt has no matching transmission attempt")
        for update_id, records in itertools.groupby(
            sorted(
                (row for row in observations if row["event_type"] == "uplink"),
                key=lambda row: (row["update_id"], row["attempt_no"]),
            ),
            key=lambda row: row["update_id"],
        ):
            attempts = list(records)
            if [row["attempt_no"] for row in attempts] != list(range(1, len(attempts) + 1)):
                raise AssertionError(f"Non-contiguous attempts for {update_id}")
            for previous, current in zip(attempts, attempts[1:]):
                delta = (
                    datetime.fromisoformat(current["observed_bdt"])
                    - datetime.fromisoformat(previous["observed_bdt"])
                ).total_seconds()
                if delta != 3:
                    raise AssertionError(f"Retry interval is not three seconds for {update_id}")
        if connection.execute(
            "PRAGMA foreign_key_check(landing_table_update_observation)"
        ).fetchall():
            raise AssertionError("Foreign key errors in landing retry observations")
    except Exception:
        connection.execute("ROLLBACK TO sbc_landing_retry_migration")
        connection.execute("RELEASE sbc_landing_retry_migration")
        raise
    else:
        connection.execute("RELEASE sbc_landing_retry_migration")
    finally:
        connection.row_factory = previous_factory


def derive_service_intervals(
    connection: sqlite3.Connection, *, actual: bool,
) -> dict[str, list[ServiceInterval]]:
    table, kind, prefix = (
        ("realtime_topology", "实时", "actual") if actual
        else ("planned_topology", "规划", "planned")
    )
    topologies = connection.execute(f"SELECT * FROM {table} ORDER BY start_bdt").fetchall()
    links = connection.execute(
        f"SELECT * FROM ground_link_topology WHERE {prefix}_start_bdt IS NOT NULL "
        + ("AND feeder_connectivity = '连通'" if actual else "")
    ).fetchall()
    boundaries = {0, 86400000}
    for row in topologies:
        boundaries.update((elapsed_ms(row["start_bdt"]), elapsed_ms(row["end_bdt"])))
    for row in links:
        boundaries.update((elapsed_ms(row[f"{prefix}_start_bdt"]),
                           elapsed_ms(row[f"{prefix}_end_bdt"])))
    path_maps = {}
    for topology in topologies:
        adjacency = {sat: set() for sat in satellite_ids()}
        for edge in connection.execute(
            "SELECT * FROM topology_edge WHERE topology_kind=? AND topology_id=? AND is_connected=1",
            (kind, topology["topology_id"]),
        ):
            adjacency[edge["source_satellite_id"]].add(edge["destination_satellite_id"])
        path_maps[topology["topology_id"]] = {
            sat: reachable_paths(adjacency, sat) for sat in satellite_ids()
        }
    result: dict[str, list[ServiceInterval]] = {sat: [] for sat in satellite_ids()}
    held: dict[str, LandingChoice | None] = {sat: None for sat in satellite_ids()}
    fault3_start_ms = elapsed_ms(bdt(FAULT3_START))
    fault3_end_ms = elapsed_ms(bdt(FAULT3_END))
    blackout_sources: set[str] = set()
    if actual:
        row = connection.execute(
            "SELECT value FROM simulation_metadata WHERE key='observed_keepalive_blackout_sources'"
        ).fetchone()
        if row is not None and row[0]:
            blackout_sources = {sat for sat in row[0].split(",") if sat}
    times = sorted(boundaries)
    for start, end in zip(times, times[1:]):
        topology = next(row for row in topologies
                        if elapsed_ms(row["start_bdt"]) <= start < elapsed_ms(row["end_bdt"]))
        active = [row for row in links
                  if elapsed_ms(row[f"{prefix}_start_bdt"]) <= start
                  and elapsed_ms(row[f"{prefix}_end_bdt"]) >= end]
        for sat in satellite_ids():
            paths = path_maps[topology["topology_id"]][sat]
            reachable = [row for row in active if row["landing_satellite_id"] in paths]
            current = held[sat]
            # Sticky: keep the held landing while its feeder arc is still active
            # and the satellite can still reach it. Only re-select from empty.
            if current is not None and any(
                row["ground_link_id"] == current.ground_link_id for row in reachable
            ):
                best_row = next(
                    row for row in reachable if row["ground_link_id"] == current.ground_link_id
                )
            elif reachable:
                best_row = min(
                    reachable,
                    key=lambda row: (len(paths[row["landing_satellite_id"]]),
                                     row["landing_satellite_id"], row["gateway_id"]),
                )
                current = LandingChoice(best_row["ground_link_id"], paths[best_row["landing_satellite_id"]])
                held[sat] = current
            else:
                best_row = None
                current = None
                held[sat] = None
            if actual and sat in blackout_sources and start < fault3_end_ms and end > fault3_start_ms:
                best_row = None
                current = None
                held[sat] = None
            choices = (
                (LandingChoice(best_row["ground_link_id"], paths[best_row["landing_satellite_id"]]),)
                if best_row is not None
                else ()
            )
            intervals = result[sat]
            if intervals and intervals[-1].choices == choices:
                intervals[-1].end_ms = end
            else:
                intervals.append(ServiceInterval(start, end, choices))
    return result


def insert_temporal_services(connection: sqlite3.Connection) -> None:
    planned = derive_service_intervals(connection, actual=False)
    actual = derive_service_intervals(connection, actual=True)
    links = {row["ground_link_id"]: row for row in connection.execute("SELECT * FROM ground_link_topology")}
    for sat, intervals in actual.items():
        planned_index = 0
        was_unexpected_outage = False
        keepalive_segments: list[list[object]] = []
        for interval in intervals:
            selected_id = None
            for rank, choice in enumerate(interval.choices):
                link = links[choice.ground_link_id]
                landing = choice.path[-1]
                plane, slot = int(landing[1:3]), int(landing[3:5])
                cursor = connection.execute(
                    """INSERT INTO keepalive_landing_candidate(
                        source_satellite_id, landing_satellite_id, gateway_id,
                        qv_address, landing_address, priority, is_selected, route_path_json,
                        valid_start_bdt, valid_end_bdt, ground_link_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (sat, landing, link["gateway_id"], f"0x{plane:02X}",
                     f"0x{plane:02X}{slot:02X}", len(choice.path) - 1, int(rank == 0),
                     json.dumps(choice.path, separators=(",", ":")),
                     time_at_ms(interval.start_ms), time_at_ms(interval.end_ms), choice.ground_link_id),
                )
                if rank == 0:
                    selected_id = cursor.lastrowid
                    keepalive_segments.append([
                        interval.start_ms,
                        interval.end_ms,
                        selected_id,
                    ])
                    connection.execute(
                        """INSERT INTO station_selection_route(route_start_bdt, route_end_bdt,
                            constellation_type, satellite_id, gateway_id, selection_strategy,
                            selected_candidate_id) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (time_at_ms(interval.start_ms), time_at_ms(interval.end_ms), CONSTELLATION,
                         sat, link["gateway_id"], "本星优先;最少跳数;落地星ID和站ID字典序", selected_id),
                    )
            start = interval.start_ms
            while start < interval.end_ms:
                while planned[sat][planned_index].end_ms <= start:
                    planned_index += 1
                theory = planned[sat][planned_index]
                end = min(interval.end_ms, theory.end_ms)
                duration = (end - start) / 1000
                theoretical_local = bool(theory.choices and len(theory.choices[0].path) == 1)
                actual_local = bool(interval.choices and len(interval.choices[0].path) == 1)
                unexpected_outage = bool(theory.choices and not interval.choices)
                selected_link = links[interval.choices[0].ground_link_id] if interval.choices else None
                connection.execute(
                    """INSERT INTO connectionless_continuity_statistics(
                        connected_segment_name, theoretical_start_bdt, theoretical_end_bdt,
                        satellite_id, feeder_start_bdt, feeder_end_bdt,
                        local_theoretical_duration_seconds, cross_satellite_theoretical_duration_seconds,
                        local_actual_duration_seconds, cross_satellite_actual_duration_seconds,
                        interruption_count, planned_unavailable_duration_seconds,
                        actual_unavailable_duration_seconds, selected_candidate_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (f"SEG-{sat}-{start:08d}", time_at_ms(start), time_at_ms(end), sat,
                     selected_link["actual_start_bdt"] if selected_link else None,
                     selected_link["actual_end_bdt"] if selected_link else None,
                     duration if theoretical_local else 0,
                     duration if theory.choices and not theoretical_local else 0,
                     duration if actual_local else 0,
                     duration if interval.choices and not actual_local else 0,
                     int(unexpected_outage and not was_unexpected_outage),
                     0 if theory.choices else duration, 0 if interval.choices else duration, selected_id),
                )
                was_unexpected_outage = unexpected_outage
                start = end
        if keepalive_segments:
            merged_segments: list[tuple[int, int, int]] = []
            for start_ms, end_ms, selected_candidate_id in keepalive_segments:
                if merged_segments and merged_segments[-1][1] == start_ms:
                    prev_start, _, prev_selected = merged_segments[-1]
                    merged_segments[-1] = (prev_start, end_ms, prev_selected)
                else:
                    merged_segments.append((start_ms, end_ms, selected_candidate_id))
            connection.executemany(
                """INSERT INTO keepalive_statistics(satellite_id, keepalive_start_bdt,
                    keepalive_end_bdt, selected_candidate_id) VALUES (?, ?, ?, ?)""",
                [
                    (sat, time_at_ms(start_ms), time_at_ms(end_ms), selected_candidate_id)
                    for start_ms, end_ms, selected_candidate_id in merged_segments
                ],
            )


def insert_operational_baseline(
    connection: sqlite3.Connection,
    arcs: list[tuple[str, str, str, str]],
    scenario: FaultScenario,
) -> None:
    baseline_events = [
        (
            satellite_name(sat_a),
            sat_a,
            laser_a,
            satellite_name(sat_b),
            sat_b,
            laser_b,
            bdt(START_BDT),
            "连通",
            10000,
        )
        for sat_a, laser_a, sat_b, laser_b in arcs
    ]
    baseline_events.extend(
        (satellite_name(source), source, source_laser,
         satellite_name(destination), destination, destination_laser,
         bdt(event_time), status, rate)
        for event_time, status, rate in (
            (SPLIT_TOPOLOGY_START, "中断", 0),
            (SPLIT_TOPOLOGY_END, "连通", 10000),
        )
        for source, source_laser, destination, destination_laser in arcs
        if ISOLATED_SATELLITE in (source, destination)
    )
    connection.executemany(
        """
        INSERT INTO laser_link_event(
            satellite_a_name, satellite_a_id, laser_a_id, satellite_b_name,
            satellite_b_id, laser_b_id, changed_bdt, link_status, link_rate_mbps
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        baseline_events,
    )
    laser_fault_events = [
        (
            satellite_name(source),
            source,
            source_laser,
            satellite_name(destination),
            destination,
            destination_laser,
            bdt(event_time),
            status,
            rate,
        )
        for source, source_laser, destination, destination_laser in arcs
        if scenario.laser_fault_satellite in (source, destination)
        for event_time, status, rate in (
            (FAULT1_START, "中断", 0),
            (FAULT1_END, "连通", 10000),
        )
    ]
    connection.executemany(
        """
        INSERT INTO laser_link_event(
            satellite_a_name, satellite_a_id, laser_a_id, satellite_b_name,
            satellite_b_id, laser_b_id, changed_bdt, link_status, link_rate_mbps
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        laser_fault_events,
    )

    satellites = {
        row["satellite_id"]: row
        for row in connection.execute(
            "SELECT satellite_id, resource_name, business_ipv4 FROM satellite_basic_info"
        )
    }
    isolation_neighbors = sorted(
        destination
        for source, _, destination, _ in arcs
        if source == ISOLATED_SATELLITE
    )
    packetin_rows = []
    packet_sequence = 100001

    def append_packetin(
        *,
        event_time: datetime,
        event_type: str,
        affected_link: str,
        message_content: str,
    ) -> None:
        event_time = min(event_time, END_BDT - timedelta(milliseconds=1))
        delivery = connection.execute(
            """SELECT source_satellite_id, candidate_id, valid_start_bdt
               FROM keepalive_landing_candidate
               WHERE is_selected=1 AND valid_end_bdt>?
               ORDER BY valid_start_bdt, source_satellite_id LIMIT 1""",
            (bdt(event_time),),
        ).fetchone()
        if delivery is None:
            raise ValueError(f"No PacketIn delivery path after {event_time}")
        reporter = delivery["source_satellite_id"]
        received = max(bdt(event_time), delivery["valid_start_bdt"])
        packetin_rows.append(
            (
                CONSTELLATION,
                "LINK_STATE",
                satellites[reporter]["business_ipv4"],
                6633,
                "10.255.0.1",
                6633,
                packet_sequence_map[0],
                message_content,
                received,
                event_type,
                affected_link,
                bdt(event_time),
                reporter,
                delivery["candidate_id"],
            )
        )
        packet_sequence_map[0] += 1

    packet_sequence_map = [packet_sequence]
    for event_time, event_type in (
        (SPLIT_TOPOLOGY_START, "LINK_DOWN"),
        (SPLIT_TOPOLOGY_END, "LINK_UP"),
    ):
        for neighbor in isolation_neighbors:
            append_packetin(
                event_time=event_time,
                event_type=event_type,
                affected_link=f"{ISOLATED_SATELLITE}->{neighbor}",
                message_content=f"{ISOLATED_SATELLITE}到{neighbor}的{event_type}消息",
            )
    append_packetin(
        event_time=FAULT1_START,
        event_type="LINK_DOWN",
        affected_link=f"{scenario.laser_fault_satellite}<->NEIGHBORS",
        message_content=f"{scenario.laser_fault_satellite}相关激光链路状态变化消息",
    )
    append_packetin(
        event_time=FAULT1_END,
        event_type="LINK_UP",
        affected_link=f"{scenario.laser_fault_satellite}<->NEIGHBORS",
        message_content=f"{scenario.laser_fault_satellite}相关激光链路状态恢复消息",
    )
    append_packetin(
        event_time=FAULT3_START,
        event_type="ROUTE_ABNORMAL",
        affected_link=f"TRANSIT:{scenario.route_loss_satellite}",
        message_content=f"经{scenario.route_loss_satellite}转发路径可达性变化消息",
    )
    append_packetin(
        event_time=FAULT3_END,
        event_type="ROUTE_RECOVER",
        affected_link=f"TRANSIT:{scenario.route_loss_satellite}",
        message_content=f"经{scenario.route_loss_satellite}转发路径可达性恢复消息",
    )
    append_packetin(
        event_time=datetime.fromisoformat(
            connection.execute(
                "SELECT actual_start_bdt FROM ground_link_topology WHERE ground_link_id=?",
                (scenario.feeder_fault_link_id,),
            ).fetchone()[0]
        ),
        event_type="FEEDER_DOWN",
        affected_link=scenario.feeder_fault_link_name,
        message_content=f"{scenario.feeder_fault_landing_satellite}经{scenario.feeder_fault_gateway_id}馈电状态变化消息",
    )
    append_packetin(
        event_time=datetime.fromisoformat(
            connection.execute(
                "SELECT actual_end_bdt FROM ground_link_topology WHERE ground_link_id=?",
                (scenario.feeder_fault_link_id,),
            ).fetchone()[0]
        ),
        event_type="FEEDER_UP",
        affected_link=scenario.feeder_fault_link_name,
        message_content=f"{scenario.feeder_fault_landing_satellite}经{scenario.feeder_fault_gateway_id}馈电状态恢复消息",
    )
    connection.executemany(
        """
        INSERT INTO packetin_message(
            planning_constellation, protocol, source_ip, source_port,
            destination_ip, destination_port, message_sequence, message_content,
            received_bdt, event_type, affected_link, occurred_bdt,
            reporting_satellite_id, selected_candidate_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        packetin_rows,
    )
    connection.executemany(
        """
        INSERT INTO packet_log(
            planning_constellation, protocol, source_ip, source_port,
            destination_ip, destination_port, message_sequence, message_content,
            received_bdt
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [row[:9] for row in packetin_rows],
    )

    measurement_rows = [
        (
            CONSTELLATION,
            "星载路由器",
            ISOLATED_SATELLITE,
            "SR3_TOPOLOGY",
            bdt(SPLIT_TOPOLOGY_START),
        ),
        (
            CONSTELLATION,
            "星载路由器",
            ISOLATED_SATELLITE,
            "SR3_TOPOLOGY",
            bdt(SPLIT_TOPOLOGY_END),
        ),
    ]
    connection.executemany(
        """
        INSERT INTO measurement_query(
            planning_constellation, node_type, node_id, query_type, received_bdt
        ) VALUES (?, ?, ?, ?, ?)
        """,
        measurement_rows,
    )
    connection.executemany(
        """
        INSERT INTO network_alarm(
            alarm_id, alarm_title, alarm_level, alarm_type, alarm_status, occurred_bdt,
            object_type, network_element_name, network_element_device_type, located_object_name,
            source_type, additional_info, cause_description, resolved_bdt
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                "ALM-20260808-0001",
                "保活路径可达性波动",
                "严重",
                "链路状态告警",
                "已清除",
                bdt(FAULT1_START),
                "卫星",
                scenario.laser_fault_satellite,
                "星载路由器",
                f"{scenario.laser_fault_satellite}相关链路",
                "自动检测",
                "该星相关链路状态变化期间，保活存在缺失现象",
                "现象待排查",
                bdt(FAULT1_END),
            ),
            (
                "ALM-20260808-0002",
                "馈电通断异常",
                "一般",
                "馈电链路告警",
                "已清除",
                connection.execute(
                    "SELECT actual_start_bdt FROM ground_link_topology WHERE ground_link_id=?",
                    (scenario.feeder_fault_link_id,),
                ).fetchone()[0],
                "星地链路",
                scenario.feeder_fault_link_name,
                "协议网关",
                scenario.feeder_fault_landing_satellite,
                "自动检测",
                "该馈电弧段内无有效保活回传",
                "现象待排查",
                connection.execute(
                    "SELECT actual_end_bdt FROM ground_link_topology WHERE ground_link_id=?",
                    (scenario.feeder_fault_link_id,),
                ).fetchone()[0],
            ),
            (
                "ALM-20260808-0003",
                "转发路径稳定性告警",
                "提醒",
                "路由可达告警",
                "已清除",
                bdt(FAULT3_START),
                "卫星",
                scenario.route_loss_satellite,
                "星载路由器",
                f"经{scenario.route_loss_satellite}转发路径",
                "自动检测",
                "相关路径保活统计出现阶段性回落",
                "现象待排查",
                bdt(FAULT3_END),
            ),
        ],
    )
    connection.executemany(
        """
        INSERT INTO satellite_historical_alarm(
            alarm_id, model_code, model_name, subsystem_name, device_name,
            alarm_message, alarm_level, occurred_bdt, satellite_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                "SAT-ALM-20260808-0306-01",
                "SIM-HIS-001",
                "链路状态异常",
                "星间链路子系统",
                "激光终端组",
                "检测到链路状态变化窗口内保活回传缺失",
                "严重",
                bdt(FAULT1_START),
                scenario.laser_fault_satellite,
            ),
            (
                "SAT-ALM-20260808-ROUTE-01",
                "SIM-HIS-002",
                "转发路径异常",
                "路由子系统",
                "转发表模块",
                "经该星转发的保活存在阶段性缺失",
                "一般",
                bdt(FAULT3_START),
                scenario.route_loss_satellite,
            ),
        ],
    )
    connection.executemany(
        """
        INSERT INTO measurement_anomaly_alarm(
            occurred_bdt, link_source, link_destination, link_delay_ms
        ) VALUES (?, ?, ?, ?)
        """,
        [
            (bdt(FAULT1_START + timedelta(minutes=8)), scenario.laser_fault_satellite, "A0206", 487.5),
            (bdt(FAULT3_START + timedelta(minutes=12)), "A0202", scenario.route_loss_satellite, 533.2),
            (bdt(FAULT3_START + timedelta(minutes=28)), "A0401", scenario.feeder_fault_landing_satellite, 462.7),
        ],
    )


def insert_telemetry(connection: sqlite3.Connection) -> None:
    router_rows = []
    for hour in range(24):
        reported = START_BDT + timedelta(hours=hour)
        for sat_id in satellite_ids():
            ip = f"10.{int(sat_id[1:3])}.{int(sat_id[3:5])}.1"
            landing = connection.execute(
                """SELECT landing_satellite_id FROM keepalive_landing_candidate
                   WHERE source_satellite_id=? AND is_selected=1
                   AND valid_start_bdt<=? AND valid_end_bdt>?""",
                (sat_id, bdt(reported), bdt(reported)),
            ).fetchone()
            router_rows.append(
                (bdt(reported), sat_id, "TASK-KEEPALIVE-20260808", ip,
                 "RTR-LANDING-MODE", "当前落地方式",
                 "0" if landing is None else ("1" if landing[0] == sat_id else "2"),
                 "无可达馈电" if landing is None else ("本星落地" if landing[0] == sat_id else "跨星落地"),
                 "正常")
            )
            router_rows.extend(
                [
                    (
                        bdt(reported),
                        sat_id,
                        "TASK-KEEPALIVE-20260808",
                        ip,
                        "RTR-CPU",
                        "CPU利用率",
                        str(28 + (hour + int(sat_id[3:5])) % 17),
                        str(28 + (hour + int(sat_id[3:5])) % 17),
                        "正常",
                    ),
                    (
                        bdt(reported),
                        sat_id,
                        "TASK-KEEPALIVE-20260808",
                        ip,
                        "RTR-ROUTE-MODE",
                        "无连接路由模式",
                        "1",
                        "启用",
                        "正常",
                    ),
                ]
            )
    connection.executemany(
        """
        INSERT INTO router_telemetry(
            reported_bdt, telemetry_source, task_id, satellite_ip,
            parameter_code, parameter_name, raw_value, parsed_value, parameter_result
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        router_rows,
    )

    laser_rows = []
    for hour in range(24):
        reported = START_BDT + timedelta(hours=hour)
        for sat_id in satellite_ids():
            ip = f"10.{int(sat_id[1:3])}.{int(sat_id[3:5])}.1"
            for direction in ("UP", "DOWN", "LEFT", "RIGHT"):
                terminal_id = f"{sat_id}-L-{direction}"
                event = connection.execute(
                    """SELECT link_status FROM laser_link_event
                       WHERE laser_a_id=? AND changed_bdt<=? ORDER BY changed_bdt DESC LIMIT 1""",
                    (terminal_id, bdt(reported)),
                ).fetchone()
                locked = event is not None and event[0] == "连通"
                laser_rows.append(
                    (
                        bdt(reported),
                        terminal_id,
                        "TASK-LASER-20260808",
                        ip,
                        "LASER-LOCK",
                        "通信译码锁定状态",
                        str(int(locked)),
                        "锁定" if locked else ("空闲" if event is None else "规划断链"),
                        "正常",
                        terminal_id,
                    )
                )
    connection.executemany(
        """
        INSERT INTO laser_telemetry(
            reported_bdt, telemetry_source, task_id, satellite_ip,
            parameter_code, parameter_name, raw_value, parsed_value,
            parameter_result, laser_terminal_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        laser_rows,
    )


def verify_temporal_services(connection: sqlite3.Connection) -> None:
    for source, (table, fields) in FIELD_MAP.items():
        columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
        missing = {column for _, column in fields if column is not None} - columns
        if missing:
            raise AssertionError(f"{source}: missing business columns {missing}")

    links = {row["ground_link_id"]: row for row in connection.execute("SELECT * FROM ground_link_topology")}
    if not links or any(
        not (bdt(START_BDT) <= row["planned_start_bdt"] < row["planned_end_bdt"] <= bdt(END_BDT))
        or row["planned_start_bdt"] != row["actual_start_bdt"]
        or row["planned_end_bdt"] != row["actual_end_bdt"]
        for row in links.values()
    ):
        raise AssertionError("Invalid no-fault feeder intervals")

    # Tracking-plan mutual exclusion: no station or satellite double-booked.
    for dimension, column in (("station", "gateway_id"), ("satellite", "landing_satellite_id")):
        for key, in connection.execute(
            f"SELECT DISTINCT {column} FROM ground_link_topology"
        ):
            ordered = sorted(
                (row for row in links.values() if row[column] == key),
                key=lambda row: row["actual_start_bdt"],
            )
            for previous, current in zip(ordered, ordered[1:]):
                if current["actual_start_bdt"] < previous["actual_end_bdt"]:
                    raise AssertionError(
                        f"Tracking plan double-books {dimension} {key}: "
                        f"{previous['tracking_arc_id']} vs {current['tracking_arc_id']}"
                    )

    snapshots = []
    for topology in connection.execute("SELECT * FROM realtime_topology ORDER BY start_bdt"):
        adjacency = {sat: set() for sat in satellite_ids()}
        for row in connection.execute(
            "SELECT * FROM topology_edge WHERE topology_kind='实时' AND topology_id=? AND is_connected=1",
            (topology["topology_id"],),
        ):
            adjacency[row["source_satellite_id"]].add(row["destination_satellite_id"])
        matrix = json.loads(topology["matrix_json"])
        if matrix_json(adjacency) != json.dumps(matrix, separators=(",", ":")):
            raise AssertionError("Matrix/edge mismatch")
        snapshots.append((topology, adjacency, {sat: reachable_paths(adjacency, sat) for sat in satellite_ids()}))
    selected = {}
    previous_end = {}
    for candidate in connection.execute(
        "SELECT * FROM keepalive_landing_candidate ORDER BY source_satellite_id, valid_start_bdt, is_selected DESC"
    ):
        link = links[candidate["ground_link_id"]]
        start, end = candidate["valid_start_bdt"], candidate["valid_end_bdt"]
        path = json.loads(candidate["route_path_json"])
        if not (path and path[0] == candidate["source_satellite_id"]
                and path[-1] == candidate["landing_satellite_id"] == link["landing_satellite_id"]
                and candidate["gateway_id"] == link["gateway_id"]
                and link["actual_start_bdt"] <= start < end <= link["actual_end_bdt"]
                and candidate["priority"] == len(path) - 1):
            raise AssertionError(f"Invalid feeder/path association: {candidate['candidate_id']}")
        for topology, adjacency, _ in snapshots:
            if topology["start_bdt"] < end and topology["end_bdt"] > start:
                if any(destination not in adjacency[source] for source, destination in zip(path, path[1:])):
                    raise AssertionError(f"Route uses disabled direction: {candidate['candidate_id']}")
        if candidate["is_selected"]:
            sat = candidate["source_satellite_id"]
            if previous_end.get(sat, start) > start:
                raise AssertionError("Overlapping selected routes")
            previous_end[sat] = end
            selected[candidate["candidate_id"]] = candidate

    route_rows = connection.execute("SELECT * FROM station_selection_route").fetchall()
    if len(route_rows) != len(selected):
        raise AssertionError("station_selection_route: selected route count mismatch")
    if len({row["selected_candidate_id"] for row in route_rows}) != len(selected):
        raise AssertionError("station_selection_route: duplicated or missing selected routes")
    for row in route_rows:
        candidate = selected[row["selected_candidate_id"]]
        if (row["satellite_id"], row["route_start_bdt"], row["route_end_bdt"]) != (
            candidate["source_satellite_id"], candidate["valid_start_bdt"], candidate["valid_end_bdt"]
        ):
            raise AssertionError("station_selection_route: time/source mismatch")
        if row["gateway_id"] != candidate["gateway_id"]:
            raise AssertionError("Station route gateway mismatch")

    keepalive_rows = connection.execute(
        "SELECT * FROM keepalive_statistics ORDER BY satellite_id, keepalive_start_bdt"
    ).fetchall()
    previous_end_by_sat: dict[str, str] = {}
    for row in keepalive_rows:
        candidate = selected.get(row["selected_candidate_id"])
        if candidate is None:
            raise AssertionError("keepalive_statistics: unknown selected candidate")
        if row["satellite_id"] != candidate["source_satellite_id"]:
            raise AssertionError("keepalive_statistics: satellite mismatch")
        if not (candidate["valid_start_bdt"] <= row["keepalive_start_bdt"] < candidate["valid_end_bdt"]):
            raise AssertionError("keepalive_statistics: start not covered by selected candidate")
        previous_end = previous_end_by_sat.get(row["satellite_id"])
        if previous_end is not None and previous_end > row["keepalive_start_bdt"]:
            raise AssertionError("keepalive_statistics: overlapping segments")
        previous_end_by_sat[row["satellite_id"]] = row["keepalive_end_bdt"]
    if connection.execute("SELECT COUNT(*) FROM v_selected_keepalive_landing").fetchone()[0] != len(selected):
        raise AssertionError("Temporal feeder view duplicates or loses selected routes")
    fault3_start_ms = elapsed_ms(bdt(FAULT3_START))
    fault3_end_ms = elapsed_ms(bdt(FAULT3_END))
    blackout_sources = set()
    blackout_row = connection.execute(
        "SELECT value FROM simulation_metadata WHERE key='observed_keepalive_blackout_sources'"
    ).fetchone()
    if blackout_row is not None and blackout_row[0]:
        blackout_sources = {sat for sat in blackout_row[0].split(",") if sat}

    for sat in satellite_ids():
        rows = connection.execute(
            "SELECT * FROM connectionless_continuity_statistics WHERE satellite_id=? ORDER BY theoretical_start_bdt",
            (sat,),
        ).fetchall()
        next_start = bdt(START_BDT)
        unavailable_ms = 0
        for row in rows:
            start, end = row["theoretical_start_bdt"], row["theoretical_end_bdt"]
            if start != next_start or start >= end:
                raise AssertionError(f"{sat}: statistics fail to partition day")
            next_start = end
            duration = elapsed_ms(end) - elapsed_ms(start)
            candidate = selected.get(row["selected_candidate_id"])
            if candidate is not None and not (
                candidate["source_satellite_id"] == sat
                and candidate["valid_start_bdt"] <= start < end <= candidate["valid_end_bdt"]
            ):
                raise AssertionError("Continuity row not covered by candidate")
            # Independently check reachability on every physical/topology boundary in this row.
            boundaries = {start, end}
            for link in links.values():
                boundaries.update(time for time in (link["actual_start_bdt"], link["actual_end_bdt"]) if start < time < end)
            for topology, _, _ in snapshots:
                boundaries.update(time for time in (topology["start_bdt"], topology["end_bdt"]) if start < time < end)
            for time in sorted(boundaries)[:-1]:
                _, _, paths = next(snapshot for snapshot in snapshots
                                   if snapshot[0]["start_bdt"] <= time < snapshot[0]["end_bdt"])
                active = [link for link in links.values()
                          if link["actual_start_bdt"] <= time < link["actual_end_bdt"]
                          and link["feeder_connectivity"] == "连通"
                          and link["landing_satellite_id"] in paths[sat]]
                # Sticky check: availability matches, and a held candidate stays
                # valid throughout its sub-segment (no mid-arc handover).
                is_blackout = sat in blackout_sources and fault3_start_ms <= elapsed_ms(time) < fault3_end_ms
                if not is_blackout and (candidate is None) != (not active):
                    raise AssertionError(f"{sat}: false service availability at {time}")
                if candidate is not None:
                    held_link = links[candidate["ground_link_id"]]
                    if not any(link["ground_link_id"] == held_link["ground_link_id"]
                               for link in active):
                        raise AssertionError(f"{sat}: held landing lost mid-segment at {time}")
                    if candidate["landing_satellite_id"] not in paths[sat]:
                        raise AssertionError(f"{sat}: held landing unreachable at {time}")
            actual_values = (
                round(row["local_actual_duration_seconds"] * 1000),
                round(row["cross_satellite_actual_duration_seconds"] * 1000),
                round(row["actual_unavailable_duration_seconds"] * 1000),
            )
            local = candidate is not None and candidate["landing_satellite_id"] == sat
            expected_actual = (
                duration if local else 0,
                duration if candidate is not None and not local else 0,
                duration if candidate is None else 0,
            )
            if actual_values != expected_actual or sum(actual_values) != duration:
                raise AssertionError(f"{sat}: inconsistent actual service durations")
            theoretical_values = (
                round(row["local_theoretical_duration_seconds"] * 1000),
                round(row["cross_satellite_theoretical_duration_seconds"] * 1000),
                round(row["planned_unavailable_duration_seconds"] * 1000),
            )
            if any(value < 0 for value in theoretical_values) or sum(theoretical_values) != duration:
                raise AssertionError(f"{sat}: inconsistent theoretical service durations")
            unavailable_ms += actual_values[2]
            if candidate is None:
                if row["feeder_start_bdt"] is not None or row["feeder_end_bdt"] is not None:
                    raise AssertionError("Unavailable service must not have a feeder interval")
            else:
                link = links[candidate["ground_link_id"]]
                if (row["feeder_start_bdt"], row["feeder_end_bdt"]) != (
                    link["actual_start_bdt"], link["actual_end_bdt"]
                ):
                    raise AssertionError("Continuity feeder times mismatch")
        if next_start != bdt(END_BDT):
            raise AssertionError(f"{sat}: missing end-of-day statistics")
        gap_ms = sum(round(row[0] * 1000) for row in connection.execute(
            "SELECT interruption_seconds FROM v_keepalive_interruptions WHERE satellite_id=?", (sat,)
        ))
        if gap_ms != unavailable_ms:
            raise AssertionError(f"{sat}: interruption view does not match unavailable duration")

    for event in connection.execute("SELECT * FROM packetin_message"):
        candidate = selected[event["selected_candidate_id"]]
        if not (event["occurred_bdt"] <= event["received_bdt"]
                and candidate["source_satellite_id"] == event["reporting_satellite_id"]
                and candidate["valid_start_bdt"] <= event["received_bdt"] < candidate["valid_end_bdt"]):
            raise AssertionError("PacketIn cannot be delivered on recorded route")
        packet = connection.execute("SELECT * FROM packet_log WHERE message_sequence=?",
                                    (event["message_sequence"],)).fetchone()
        if packet is None or any(packet[key] != event[key] for key in packet.keys() if key != "packet_log_id"):
            raise AssertionError("PacketIn and packet log mismatch")
    for telemetry in connection.execute("SELECT * FROM laser_telemetry"):
        event = connection.execute(
            "SELECT link_status FROM laser_link_event WHERE laser_a_id=? AND changed_bdt<=? "
            "ORDER BY changed_bdt DESC LIMIT 1",
            (telemetry["laser_terminal_id"], telemetry["reported_bdt"]),
        ).fetchone()
        if telemetry["raw_value"] != str(int(event is not None and event[0] == "连通")):
            raise AssertionError("Laser telemetry/event inconsistency")


def verify_database(connection: sqlite3.Connection, scenario: FaultScenario) -> None:
    expected_counts = {
        "satellite_basic_info": 60,
        "protocol_gateway_basic_info": 3,
        "laser_terminal": 240,
        "planned_topology": 3,
        "realtime_topology": 7,
        "measurement_query": 2,
        "router_telemetry": 4320,
        "laser_telemetry": 5760,
        "satellite_om_log": 0,
        "simulation_fault": 0,
        "simulation_fault_evidence": 0,
    }
    for table, expected_count in expected_counts.items():
        actual_count = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        if actual_count != expected_count:
            raise AssertionError(f"{table}: expected {expected_count}, got {actual_count}")
    packetin_count = connection.execute("SELECT COUNT(*) FROM packetin_message").fetchone()[0]
    packetlog_count = connection.execute("SELECT COUNT(*) FROM packet_log").fetchone()[0]
    if packetin_count != 12 or packetlog_count != 12:
        raise AssertionError(f"PacketIn/packet_log expected 12 rows, got {packetin_count}/{packetlog_count}")
    if connection.execute("SELECT COUNT(*) FROM network_alarm").fetchone()[0] != 3:
        raise AssertionError("network_alarm: expected 3 rows")
    if connection.execute("SELECT COUNT(*) FROM satellite_historical_alarm").fetchone()[0] != 2:
        raise AssertionError("satellite_historical_alarm: expected 2 rows")
    if connection.execute("SELECT COUNT(*) FROM measurement_anomaly_alarm").fetchone()[0] != 3:
        raise AssertionError("measurement_anomaly_alarm: expected 3 rows")
    if connection.execute("SELECT COUNT(*) FROM laser_link_event").fetchone()[0] <= 232:
        raise AssertionError("laser_link_event: fault events were not injected")

    matrix_rows = connection.execute(
        """
        SELECT '规划' AS topology_kind, topology_id, matrix_json
        FROM planned_topology
        UNION ALL
        SELECT '实时' AS topology_kind, topology_id, matrix_json
        FROM realtime_topology
        """
    ).fetchall()
    for topology_kind, topology_id, encoded_matrix in matrix_rows:
        matrix = json.loads(encoded_matrix)
        if len(matrix) != 60 or any(len(row) != 60 for row in matrix):
            raise AssertionError(f"{topology_id}: topology matrix is not 60x60")
        if any(matrix[index][index] != -1 for index in range(60)):
            raise AssertionError(f"{topology_id}: diagonal values must be -1")
        matrix_connected = sum(value == 1 for row in matrix for value in row)
        edge_connected = connection.execute(
            """SELECT COUNT(*) FROM topology_edge
               WHERE topology_kind=? AND topology_id=? AND is_connected=1""",
            (topology_kind, topology_id),
        ).fetchone()[0]
        if matrix_connected != edge_connected:
            raise AssertionError(f"{topology_id}: matrix/edge connected count mismatch")
    matrix_by_id = {
        topology_id: json.loads(encoded_matrix)
        for _, topology_id, encoded_matrix in matrix_rows
    }
    planned_expected_ones = {
        "PLAN-FULL-20260808-001": 220,
        "PLAN-ISOLATE-20260808-001": 214,
        "PLAN-FULL-20260808-002": 220,
    }
    for topology_id, expected_count in planned_expected_ones.items():
        matrix = matrix_by_id[topology_id]
        actual_count = sum(value == 1 for row in matrix for value in row)
        if actual_count != expected_count:
            raise AssertionError(
                f"{topology_id}: expected {expected_count} connections, got {actual_count}"
            )
    for topology_id in matrix_by_id:
        matrix = matrix_by_id[topology_id]
        if any(
            matrix[row][column] != matrix[column][row]
            for row in range(60)
            for column in range(60)
        ):
            raise AssertionError(f"{topology_id}: topology must be symmetric")
    isolated_index = satellite_ids().index(ISOLATED_SATELLITE)
    for topology_id in ("PLAN-ISOLATE-20260808-001", "REAL-ISOLATE-20260808-001"):
        matrix = matrix_by_id[topology_id]
        isolated_neighbors = [
            satellite_ids()[column]
            for column in range(60)
            if column != isolated_index and matrix[isolated_index][column] == 1
        ]
        if isolated_neighbors:
            raise AssertionError(
                f"{topology_id}: {ISOLATED_SATELLITE} must have no neighbors, got {isolated_neighbors}"
            )

    packetin_rows = connection.execute(
        """
        SELECT event_type, affected_link, occurred_bdt
        FROM packetin_message
        ORDER BY message_sequence
        """
    ).fetchall()
    expected_links = sorted(["A0603->A0602", "A0603->A0604", "A0603->A0503"])
    actual_links = sorted({affected_link for _, affected_link, _ in packetin_rows})
    if not set(expected_links).issubset(actual_links):
        raise AssertionError(f"PacketIn missing isolation links, got {actual_links}")
    expected_events = {
        ("LINK_DOWN", link, bdt(SPLIT_TOPOLOGY_START)) for link in expected_links
    } | {("LINK_UP", link, bdt(SPLIT_TOPOLOGY_END)) for link in expected_links}
    if not expected_events.issubset({tuple(row) for row in packetin_rows}):
        raise AssertionError(f"PacketIn missing baseline topology events: {packetin_rows}")

    planned_intervals = [
        tuple(row)
        for row in connection.execute(
            """
            SELECT topology_id, start_bdt, end_bdt
            FROM planned_topology
            ORDER BY start_bdt
            """
        )
    ]
    expected_intervals = [
        ("PLAN-FULL-20260808-001", bdt(START_BDT), bdt(SPLIT_TOPOLOGY_START)),
        (
            "PLAN-ISOLATE-20260808-001",
            bdt(SPLIT_TOPOLOGY_START),
            bdt(SPLIT_TOPOLOGY_END),
        ),
        ("PLAN-FULL-20260808-002", bdt(SPLIT_TOPOLOGY_END), bdt(END_BDT)),
    ]
    if planned_intervals != expected_intervals:
        raise AssertionError(f"Unexpected planned topology intervals: {planned_intervals}")
    realtime_intervals = [
        tuple(row)
        for row in connection.execute(
            """
            SELECT topology_id, start_bdt, end_bdt
            FROM realtime_topology
            ORDER BY start_bdt
            """
        )
    ]
    expected_realtime_intervals = [
        ("REAL-FULL-20260808-001", bdt(START_BDT), bdt(SPLIT_TOPOLOGY_START)),
        (
            "REAL-ISOLATE-20260808-001",
            bdt(SPLIT_TOPOLOGY_START),
            bdt(SPLIT_TOPOLOGY_END),
        ),
        ("REAL-FULL-20260808-002", bdt(SPLIT_TOPOLOGY_END), bdt(FAULT1_START)),
        ("REAL-FLT-LASER-20260808-001", bdt(FAULT1_START), bdt(FAULT3_START)),
        ("REAL-FLT-COUPLED-20260808-001", bdt(FAULT3_START), bdt(FAULT1_END)),
        ("REAL-FLT-ROUTE-20260808-001", bdt(FAULT1_END), bdt(FAULT3_END)),
        ("REAL-FULL-20260808-003", bdt(FAULT3_END), bdt(END_BDT)),
    ]
    if realtime_intervals != expected_realtime_intervals:
        raise AssertionError(f"Unexpected realtime topology intervals: {realtime_intervals}")

    if scenario.laser_fault_satellite == scenario.route_loss_satellite:
        raise AssertionError("Fault satellites must be different")
    if scenario.route_loss_satellite in {
        row[0] for row in connection.execute("SELECT DISTINCT landing_satellite_id FROM ground_link_topology")
    }:
        raise AssertionError("Route-loss fault satellite must be non-landing")
    feeder_row = connection.execute(
        """SELECT feeder_connectivity FROM ground_link_topology WHERE ground_link_id=?""",
        (scenario.feeder_fault_link_id,),
    ).fetchone()
    if feeder_row is None or feeder_row[0] != "中断":
        raise AssertionError("Selected feeder fault arc was not marked as interrupted")

    verify_temporal_services(connection)

    foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
    if foreign_key_errors:
        raise AssertionError(f"Foreign key errors: {foreign_key_errors}")

    invalid_times = connection.execute(
        """
        SELECT 'packetin_message', received_bdt FROM packetin_message
        WHERE received_bdt < ? OR received_bdt >= ?
        UNION ALL
        SELECT 'network_alarm', occurred_bdt FROM network_alarm
        WHERE occurred_bdt < ? OR occurred_bdt >= ?
        UNION ALL
        SELECT 'laser_link_event', changed_bdt FROM laser_link_event
        WHERE changed_bdt < ? OR changed_bdt >= ?
        """,
        (bdt(START_BDT), bdt(END_BDT)) * 3,
    ).fetchall()
    if invalid_times:
        raise AssertionError(f"Rows outside simulation window: {invalid_times}")


def generate_database(workbook: Path, output: Path, force: bool) -> None:
    validate_workbook(workbook)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and not force:
        raise FileExistsError(f"{output} already exists; use --force to replace it")
    with NamedTemporaryFile(prefix=f".{output.name}.", suffix=".tmp", dir=output.parent) as temporary:
        temporary_output = Path(temporary.name)
    # A unique path avoids deleting another generator's in-progress database.

    connection = sqlite3.connect(temporary_output)
    connection.row_factory = sqlite3.Row
    try:
        connection.executescript(SCHEMA)
        insert_metadata(connection)
        insert_field_mapping(connection)
        insert_resources(connection)
        edges = build_edges()
        arcs = build_directed_arcs(edges)
        insert_topologies(connection, arcs)
        insert_ground_passes(connection)
        scenario = inject_fault_scenarios(connection, arcs)
        insert_temporal_services(connection)
        insert_operational_baseline(connection, arcs, scenario)
        insert_telemetry(connection)
        insert_landing_table_updates(connection)
        insert_onboard_routing_snapshots(connection, scenario.route_loss_satellite)
        verify_observation_tables(connection)
        verify_database(connection, scenario)
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise AssertionError("SQLite integrity check failed")
        connection.commit()
    except Exception:
        connection.close()
        temporary_output.unlink(missing_ok=True)
        raise
    connection.close()
    temporary_output.replace(output)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the SBC SQLite simulation database.")
    parser.add_argument(
        "--workbook",
        type=Path,
        default=Path("data/data_format.xlsx"),
        help="Workbook containing the source and field definitions.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/sbc_simulation_20260808.db"),
        help="SQLite database output path.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace the exact output file if it already exists.",
    )
    args = parser.parse_args()
    generate_database(args.workbook, args.output, args.force)
    print(args.output)


if __name__ == "__main__":
    main()
