---
name: figure-plot
description: 根据用户需求，查询01号卫星的遥测参数并且绘制图表.
---

# figure-plot

## 概述

当用户要求你查询某一段时间内的卫星数据并且画图时，选择本技能。本技能能够调用**data-query**工具读取数据，并且利用scripts脚本中的画图脚本进行图表绘制。

**请注意你只能处理单一遥测参数绘图需求，当用户输出两个及以上参数绘图需求时，需要告诉他一个一个来**

## 前置条件

1.在执行前请牢记在调用data-query工具时只能从可供选择的参数列表范围内选择对应的参数，以免出现工具调用错误。

2.**data-query**工具的参数为：

{"type": "function",  
     "function": {  
         "name": "data_query", "description": "查询命令，获取指定卫星遥测参数在某个时间段内的值，在要求查询的任务中优先使用",  
         "parameters": {"type": "object", "properties": {  
             "sat_id": {"type": "string", "description": "要查询的卫星编号，目前只有编号\'01\'"},  
             "para_name": {"type": "array", "description": "要查询的遥测参数名称列表,必须从指定的参数列表中选择"},  
             "start_time": {"type": "string", "description": "查询开始时间，格式为\'YYYY-MM-DD hh:mm\'"},  
             "end_time": {"type": "string", "description": "查询结束时间，格式为\'YYYY-MM-DD hh:mm\'"}  
         },"required":["sat_id","para_name","start_time","end_time"]}  
     }}

3.可供选择的参数列表是：

{"parameter_name":"sat_id",  
"description":"要查询的卫星的编号，必须在enum的可选值列表内选择，严禁出现错字、漏字等现象",  
"enum":["01"]  
}

{"parameter_name":"para_name",  
"description":"要查询的遥测参数的名称，必须在enum的可选值列表内选择，严禁出现错字、漏字等现象",  
"enum":["蓄电池A测点1","蓄电池A测点2","蓄电池B测点1","S/C相控阵天线测温点1","S/C相控阵天线测温点2","S/C相控阵天线测温点10"]  
}

查询开始时间和结束时间根据用户的需求来撰写，符合YYYY-MM-DD hh:mm格式要求即可。

## 处理步骤

1. 根据用户的需求，调用data-query工具来读取相关的参数数据。

2. 将接受到的参数数据按照要求组装为json包，存储在"skills/figure-plot/assets"文件夹下面。
   
   json格式如下：
   
   {
   
           "para_name": "遥测参数名称",
           "value": [
               {"time": "2024-01-01T00:01.0543", "point_value": 32.4},
               {"time": "2024-01-01T00:03.0632", "point_value": 33.5}
           ]
       }

3. 调用scripts脚本中的plot.py函数生成对应的图表。
   
   ```bash
    cd skills/figure-plot/scripts
   python plot.py --data json文件名称.json
   ```

将上述脚本中的“json文件名称”替换为可用的json文件路径与名称。
