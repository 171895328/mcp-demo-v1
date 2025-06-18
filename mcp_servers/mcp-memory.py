import json
import os
from mcp.server import FastMCP
from pathlib import Path
mcp = FastMCP("memory")

MEMO_PATH = os.getenv('MEMORY_FILE_PATH')

print("memory_file_path",MEMO_PATH)

import json
import os
from pathlib import Path
from mcp.server import FastMCP

mcp = FastMCP("memory")

# 获取环境变量中的文件路径
MEMO_PATH = os.getenv('MEMORY_FILE_PATH')

@mcp.tool()
def create_kg_entity(entities: list):
    """
    批量创建知识图谱实体，并将其保存到指定 JSON 文件中。
    
    Args:
        entities (list): 包含多个实体字典，每个实体字典包含：
            - entity_type (str)
            - entity_name (str)
            - entity_properties (dict)
    
    Returns:
        list: 返回成功创建的实体列表。
    """
    memory_file_path = Path(MEMO_PATH)
    memory_file_path.parent.mkdir(parents=True, exist_ok=True)

    # 读取已有实体数据（如果有）
    if memory_file_path.exists():
        with open(memory_file_path, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                data = []
    else:
        data = []

    created_entities = []

    for item in entities:
        entity_type = item.get("entity_type")
        entity_name = item.get("entity_name")
        entity_properties = item.get("entity_properties", {})

        entity = {
            "type": "entity",
            "subType": entity_type,
            "name": entity_name,
            "properties": entity_properties
        }

        data.append(entity)
        created_entities.append(entity)

        print(f"实体已添加: {entity_name}（类型: {entity_type}）")

    # 写回文件
    with open(memory_file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return created_entities



@mcp.tool()
def create_kg_relationship(relationships: list) -> list:
    """
    向知识图谱中添加一个或多个关系，并保存到 MEMORY_FILE_PATH 中。

    Args:
        relationships (list): 包含多个关系的列表，每个关系是一个 dict，格式如下：
            {
                "relation_type": "serves",                     // 关系类型：服务于
                "source_entity": "AI",                         // 起始实体：AI
                "target_entity": "主人",                      // 目标实体：您自己
                "relation_properties": {                     # 可选：关系的属性
                    "since": "2022年"
                }
            }
    Return:
        list: 添加的所有关系对象。
    """
    memory_file_path = Path(MEMO_PATH)
    memory_file_path.parent.mkdir(parents=True, exist_ok=True)

    # 加载原始文件内容
    if memory_file_path.exists():
        try:
            with open(memory_file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except json.JSONDecodeError:
            data = []
    else:
        data = []

    new_relationships = []

    for rel in relationships:
        relationship = {
            "type": "relationship",
            "subType": rel["relation_type"],
            "source": rel["source_entity"],
            "target": rel["target_entity"],
            "properties": rel.get("relation_properties", {})
        }
        data.append(relationship)
        new_relationships.append(relationship)

    # 写回文件
    with open(memory_file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"已添加 {len(new_relationships)} 个关系。")
    return new_relationships



@mcp.tool()
def read_kg() -> dict:
    """
    读取知识图谱文件，并返回其中的所有实体和关系信息。
    
    Return:
        dict: 包含所有实体和关系的字典，结构如下：
        {
            "entities": [  # 实体列表
                {
                    "type": "entity",
                    "subType": "Person",
                    "name": "张老师",
                    "properties": {"title": "教授", "department": "计算机科学与技术"}
                },
                ...
            ],
            "relationships": [  # 关系列表
                {
                    "type": "relationship",
                    "subType": "teaches",
                    "source": "张老师",
                    "target": "高等数学",
                    "properties": {"since": "2022年"}
                },
                ...
            ]
        }
    """
    memory_file_path = Path(MEMO_PATH)

    # 如果文件不存在，返回空字典
    if not memory_file_path.exists():
        print("知识图谱文件不存在")
        return {"entities": [], "relationships": []}

    # 加载图谱文件
    with open(memory_file_path, 'r', encoding='utf-8') as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            print("文件格式不正确，无法读取数据")
            return {"entities": [], "relationships": []}
    
    # 分离实体和关系
    entities = [item for item in data if item.get("type") == "entity"]
    relationships = [item for item in data if item.get("type") == "relationship"]

    return {"entities": entities, "relationships": relationships}

 
@mcp.tool()
def delete_kg_entity(entity_name: str) -> dict:
    """
    删除指定名称的实体。

    Args:
        entity_name (str): 要删除的实体名称。

    Return:
        dict: 删除状态信息。
    """
    memory_file_path = Path(MEMO_PATH)

    if not memory_file_path.exists():
        print("知识图谱文件不存在")
        return {"status": "failed", "message": "知识图谱文件不存在"}

    try:
        with open(memory_file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError:
        print("文件格式不正确，无法读取数据")
        return {"status": "failed", "message": "知识图谱文件格式错误"}

    original_len = len(data)
    data = [item for item in data if not (item.get("type") == "entity" and item.get("name") == entity_name)]

    if len(data) == original_len:
        return {"status": "not_found", "message": f"实体 '{entity_name}' 未找到"}

    with open(memory_file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"已删除实体：{entity_name}")
    return {"status": "success", "message": f"实体 '{entity_name}' 已成功删除"}


@mcp.tool()
def delete_kg_relationship(relation_type: str, source_entity: str, target_entity: str) -> dict:
    """
    删除指定关系。

    Args:
        relation_type (str): 关系类型。
        source_entity (str): 起始实体名称。
        target_entity (str): 目标实体名称。

    Return:
        dict: 删除状态信息。
    """
    memory_file_path = Path(MEMO_PATH)

    if not memory_file_path.exists():
        print("知识图谱文件不存在")
        return {"status": "failed", "message": "知识图谱文件不存在"}

    try:
        with open(memory_file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError:
        print("文件格式不正确，无法读取数据")
        return {"status": "failed", "message": "知识图谱文件格式错误"}

    original_len = len(data)
    data = [item for item in data if not (
        item.get("type") == "relationship" and 
        item.get("subType") == relation_type and 
        item.get("source") == source_entity and 
        item.get("target") == target_entity)]

    if len(data) == original_len:
        return {
            "status": "not_found",
            "message": f"关系 '{source_entity} -[{relation_type}]-> {target_entity}' 未找到"
        }

    with open(memory_file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"已删除关系：{source_entity} -> {target_entity}（类型：{relation_type}）")
    return {
        "status": "success",
        "message": f"关系 '{source_entity} -[{relation_type}]-> {target_entity}' 已成功删除"
    }


   
    
@mcp.tool()
def read_specific_entity_or_relationship(entity_name: str = None, 
                                          relation_type: str = None, 
                                          source_entity: str = None, 
                                          target_entity: str = None) -> dict:
    """
    读取指定的实体或关系。

    Args:
        entity_name (str): 实体名称（可选），如果提供则返回该实体。
        relation_type (str): 关系类型（可选），如果提供则返回该类型的所有关系。
        source_entity (str): 起始实体（可选），如果提供则返回从该实体出发的关系。
        target_entity (str): 目标实体（可选），如果提供则返回指向该实体的关系。

    Return:
        dict: 指定的实体或关系，包含详细信息。
    """
    memory_file_path = Path(MEMO_PATH)

    # 如果文件不存在，返回空字典
    if not memory_file_path.exists():
        print("知识图谱文件不存在")
        return {"entities": [], "relationships": []}

    # 加载图谱文件
    with open(memory_file_path, 'r', encoding='utf-8') as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            print("文件格式不正确，无法读取数据")
            return {"entities": [], "relationships": []}
    
    # 根据实体名称筛选实体
    if entity_name:
        entities = [item for item in data if item.get("type") == "entity" and item.get("name") == entity_name]
    else:
        entities = [item for item in data if item.get("type") == "entity"]
    
    # 根据关系类型、起始实体和目标实体筛选关系
    if relation_type and source_entity and target_entity:
        relationships = [item for item in data if (
            item.get("type") == "relationship" and
            item.get("subType") == relation_type and
            item.get("source") == source_entity and
            item.get("target") == target_entity
        )]
    elif relation_type:
        relationships = [item for item in data if item.get("type") == "relationship" and item.get("subType") == relation_type]
    elif source_entity and target_entity:
        relationships = [item for item in data if (
            item.get("type") == "relationship" and
            item.get("source") == source_entity and
            item.get("target") == target_entity
        )]
    else:
        relationships = [item for item in data if item.get("type") == "relationship"]
    
    return {"entities": entities, "relationships": relationships}

@mcp.tool()
def read_specific_entity(entity_name: str = None) -> dict:
    """
    读取指定名称的实体。

    Args:
        entity_name (str): 实体名称（可选），如果提供则返回该实体。

    Return:
        dict: 指定的实体，包含详细信息。
    """
    memory_file_path = Path(MEMO_PATH)

    # 如果文件不存在，返回空字典
    if not memory_file_path.exists():
        print("知识图谱文件不存在")
        return {"entities": [], "relationships": []}

    # 加载图谱文件
    with open(memory_file_path, 'r', encoding='utf-8') as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            print("文件格式不正确，无法读取数据")
            return {"entities": [], "relationships": []}
    
    # 根据实体名称筛选实体
    if entity_name:
        entities = [item for item in data if item.get("type") == "entity" and item.get("name") == entity_name]
    else:
        entities = [item for item in data if item.get("type") == "entity"]
    
    return {"entities": entities}


@mcp.tool()
def read_specific_relationship(relation_type: str = None, 
                               source_entity: str = None, 
                               target_entity: str = None) -> dict:
    """
    读取指定的关系。

    Args:
        relation_type (str): 关系类型（可选），如果提供则返回该类型的所有关系。
        source_entity (str): 起始实体（可选），如果提供则返回从该实体出发的关系。
        target_entity (str): 目标实体（可选），如果提供则返回指向该实体的关系。

    Return:
        dict: 指定的关系，包含详细信息。
    """
    memory_file_path = Path(MEMO_PATH)

    # 如果文件不存在，返回空字典
    if not memory_file_path.exists():
        print("知识图谱文件不存在")
        return {"entities": [], "relationships": []}

    # 加载图谱文件
    with open(memory_file_path, 'r', encoding='utf-8') as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            print("文件格式不正确，无法读取数据")
            return {"entities": [], "relationships": []}
    
    # 根据关系类型、起始实体和目标实体筛选关系
    if relation_type and source_entity and target_entity:
        relationships = [item for item in data if (
            item.get("type") == "relationship" and
            item.get("subType") == relation_type and
            item.get("source") == source_entity and
            item.get("target") == target_entity
        )]
    elif relation_type:
        relationships = [item for item in data if item.get("type") == "relationship" and item.get("subType") == relation_type]
    elif source_entity and target_entity:
        relationships = [item for item in data if (
            item.get("type") == "relationship" and
            item.get("source") == source_entity and
            item.get("target") == target_entity
        )]
    else:
        relationships = [item for item in data if item.get("type") == "relationship"]
    
    return {"relationships": relationships}



@mcp.tool()
def edit_entity(entity_name: str, new_entity_type: str = None, new_properties: dict = None) -> dict:
    """
    编辑指定名称的实体，更新其类型或属性。

    参数:
        entity_name (str): 要编辑的实体名称。
        new_entity_type (str): 新的实体类型（可选），如果提供则更新实体类型。
        new_properties (dict): 新的实体属性（可选），如果提供则更新实体的属性。

    返回:
        dict: 更新后的实体信息，如果没有找到实体则返回空字典。
    """
    memory_file_path = Path(MEMO_PATH)

    # 如果文件不存在，返回空字典
    if not memory_file_path.exists():
        print("知识图谱文件不存在")
        return {}

    # 加载图谱文件
    with open(memory_file_path, 'r', encoding='utf-8') as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            print("文件格式不正确，无法读取数据")
            return {}

    # 找到指定名称的实体
    entity_to_edit = None
    for item in data:
        if item.get("type") == "entity" and item.get("name") == entity_name:
            entity_to_edit = item
            break
    
    if not entity_to_edit:
        print(f"未找到实体：{entity_name}")
        return {}

    # 更新实体的类型和属性
    if new_entity_type:
        entity_to_edit["subType"] = new_entity_type
    if new_properties:
        entity_to_edit["properties"].update(new_properties)

    # 保存更新后的实体到文件
    with open(memory_file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"实体 '{entity_name}' 已更新。")
    return entity_to_edit


@mcp.tool()
def edit_relationship(relation_type: str, source_entity: str, target_entity: str, 
                      new_relation_type: str = None, new_relation_properties: dict = None) -> dict:
    """
    编辑指定关系，更新其类型或属性。

    参数:
        relation_type (str): 原始关系类型，例如 'teaches'。
        source_entity (str): 起始实体的名称。
        target_entity (str): 目标实体的名称。
        new_relation_type (str): 新的关系类型（可选），如果提供则更新关系类型。
        new_relation_properties (dict): 新的关系属性（可选），如果提供则更新关系的属性。

    返回:
        dict: 更新后的关系信息，如果没有找到关系则返回空字典。
    """
    memory_file_path = Path(MEMO_PATH)

    # 如果文件不存在，返回空字典
    if not memory_file_path.exists():
        print("知识图谱文件不存在")
        return {}

    # 加载图谱文件
    with open(memory_file_path, 'r', encoding='utf-8') as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            print("文件格式不正确，无法读取数据")
            return {}

    # 找到指定的关系
    relationship_to_edit = None
    for item in data:
        if item.get("type") == "relationship" and item.get("relation_type") == relation_type:
            if item.get("source_entity") == source_entity and item.get("target_entity") == target_entity:
                relationship_to_edit = item
                break
    
    if not relationship_to_edit:
        print(f"未找到关系：{source_entity} -> {target_entity}，类型：{relation_type}")
        return {}

    # 更新关系的类型和属性
    if new_relation_type:
        relationship_to_edit["relation_type"] = new_relation_type
    if new_relation_properties:
        relationship_to_edit["relation_properties"].update(new_relation_properties)

    # 保存更新后的关系到文件
    with open(memory_file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"关系已更新：{source_entity} -> {target_entity}（类型: {relation_type}）")
    return relationship_to_edit


if __name__ == "__main__":
    mcp.run(transport="stdio")
