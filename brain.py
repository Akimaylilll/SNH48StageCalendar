import json
import os
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


class Brain:
  """大脑模块，用于多轮对话记忆，从微博原文中学习公演信息"""

  def __init__(self, memory_file: str = "memory.json"):
    self.memory_file = memory_file
    self.memory = self._load_memory()

  def _load_memory(self) -> Dict[str, Any]:
    """加载memory文件，如果不存在则创建默认结构"""
    if os.path.exists(self.memory_file):
      try:
        with open(self.memory_file, "r", encoding="utf-8") as f:
          return json.load(f)
      except Exception as e:
        logger.error(f"加载memory文件失败: {e}")
        return self._create_default_memory()
    else:
      return self._create_default_memory()

  def _create_default_memory(self) -> Dict[str, Any]:
    """创建默认的memory结构"""
    return {
      "version": "1.0",
      "created_at": datetime.now().isoformat(),
      "updated_at": datetime.now().isoformat(),
      "extraction_rules": {
        "system_prompt": "你是一个专业的数据提取助手，专门从文本中提取SNH48及其姐妹团体的公演、演唱会和运动会的时间信息。",
        "rules": [],
      },
      "sessions": [],
      "known_performances": [],
      "excluded_keywords": [
        "线上直播",
        "直播",
        "云公演",
        "电视综艺",
        "路演",
        "见面会",
        "握手会",
        "足球赛",
        "直播间",
        "MINI LIVE",
        "外务",
        "运动会",
        "综艺",
        "采访",
        "特别节目",
        "访谈",
        "联播",
        "录制",
        "彩排",
      ],
      "team_aliases": {},
      "theme_normalization": {},
      "duplicate_rules": {},
    }

  def save_memory(self):
    """保存memory到文件"""
    try:
      self.memory["updated_at"] = datetime.now().isoformat()
      with open(self.memory_file, "w", encoding="utf-8") as f:
        json.dump(self.memory, f, ensure_ascii=False, indent=2)
      logger.debug(f"Memory已保存到 {self.memory_file}")
    except Exception as e:
      logger.error(f"保存memory文件失败: {e}")

  def add_session(self, texts: List[str], extracted_events: List[Dict[str, str]]):
    """添加一个新的session，保留微博原文和提取结果"""
    session = {
      "timestamp": datetime.now().isoformat(),
      "raw_texts": texts,  # 微博原文
      "extracted_events": extracted_events,  # 提取的事件
      "text_count": len(texts),
      "event_count": len(extracted_events),
    }

    self.memory.setdefault("sessions", []).append(session)

    # 只保留最近50个session
    if len(self.memory["sessions"]) > 50:
      self.memory["sessions"] = self.memory["sessions"][-50:]

    logger.info(f"添加新session: {len(texts)}条原文, {len(extracted_events)}个事件")

  def get_recent_sessions(self, count: int = 5) -> List[Dict[str, Any]]:
    """获取最近的session"""
    sessions = self.memory.get("sessions", [])
    return sessions[-count:] if sessions else []

  def get_session_context(self, count: int = 3) -> str:
    """获取最近session的上下文信息，用于提取"""
    sessions = self.get_recent_sessions(count)
    if not sessions:
      return ""

    lines = ["【历史提取记录】"]
    for i, session in enumerate(sessions, 1):
      timestamp = session.get("timestamp", "")
      event_count = session.get("event_count", 0)
      events = session.get("extracted_events", [])

      lines.append(f"\n--- 第{i}次提取 ({timestamp}) ---")
      lines.append(f"提取到 {event_count} 个事件:")

      # 显示最近的事件
      for event in events[:10]:
        time = event.get("time", "")
        theme = event.get("theme", "")
        team = event.get("team", "")
        lines.append(f"  - {time} {theme} {team}")

      if len(events) > 10:
        lines.append(f"  ... 还有 {len(events) - 10} 个")

    return "\n".join(lines)

  def learn_from_texts(
    self, texts: List[str], request_openai_func=None, data_file: str = None
  ) -> List[Dict]:
    """从微博原文中学习公演信息，使用多轮对话进行提取。
    如果指定data_file，会将提取结果与文件中当前日期之后的数据合并去重并写回。
    返回提取到的公演事件列表（含time/theme/team字段）。"""
    if not texts or not request_openai_func:
      return []

    # 合并所有文本
    combined_text = "\n".join(texts)

    # 限制文本长度
    if len(combined_text) > 5000:
      combined_text = combined_text[:5000]

    # 获取brain上下文（含session历史、已知公演、排除关键词等）
    known_context = self.get_extraction_context()

    # 从data.js中读取当前日期之后的数据作为参考上下文
    if data_file:
      try:
        data = self._read_data_file(data_file)
        if data:
          current_date = datetime.now().strftime("%Y/%m/%d")
          future_events = [
            item for item in data if item.get("time", "").split(" ")[0] >= current_date
          ]
          if future_events:
            known_context += "\n\n【data.js中已有的公演安排】\n"
            for evt in future_events[:30]:
              known_context += f"- {evt.get('time', '')} {evt.get('theme', '')} {evt.get('team', '')}\n"
            if len(future_events) > 30:
              known_context += f"  ... 还有 {len(future_events) - 30} 条\n"
            logger.info(f"已加载 {len(future_events)} 条data.js未来数据作为提取参考")
      except Exception as e:
        logger.warning(f"读取data.js未来数据作为参考失败: {e}")

    # 获取对话任务
    dialogue_tasks = self.memory.get("dialogue_tasks", {})
    tasks = dialogue_tasks.get("tasks", [])

    # 构建任务描述
    tasks_desc = "\n".join([f"{i + 1}. {task}" for i, task in enumerate(tasks)])

    # 获取提取规则
    extraction_rules = self.get_extraction_rules()
    extraction_system_prompt = extraction_rules.get(
      "system_prompt",
      "你是一个专业的数据提取助手，专门从文本中提取SNH48及其姐妹团体的公演、演唱会和运动会的时间信息。",
    )
    rules = extraction_rules.get("rules", [])
    rules_text = "\n".join([f"{i + 1}. {rule}" for i, rule in enumerate(rules)])

    # 初始化对话历史（合并提取和学习任务）
    messages = [
      {
        "role": "system",
        "content": f"""{extraction_system_prompt}

        学习任务：
        {tasks_desc}

        请严格按照要求返回JSON格式数据。

        在整个对话过程中，你需要：
        1. 第一轮：提取公演信息（含time/theme/team/type）
        2. 第二轮：识别团队别名
        3. 第三轮：识别主题变体和规范化规则
        4. 第四轮：分析去重规则和成员团队对应关系
        5. 第五轮：生成对话总结""",
      }
    ]

    # 第一轮：提取公演信息（含time/theme/team/type）
    logger.info("第一轮对话：提取公演信息")
    performances, messages = self._learn_performances(
      combined_text, known_context, rules_text, messages, request_openai_func
    )

    if not performances:
      logger.warning("第一轮未提取到任何公演信息")
      return []

    # 第二轮：基于第一轮结果，识别团队别名
    logger.info("第二轮对话：识别团队别名")
    messages = self._learn_team_aliases(
      combined_text, performances, messages, request_openai_func
    )

    # 第三轮：基于前两轮结果，识别主题变体和规范化规则
    logger.info("第三轮对话：识别主题变体和规范化规则")
    messages = self._learn_theme_normalization(
      combined_text, performances, messages, request_openai_func
    )

    # 第四轮：基于前三轮结果，分析去重规则
    logger.info("第四轮对话：分析去重规则")
    self._learn_deduplication_rules(
      combined_text, performances, messages, request_openai_func
    )

    # 生成对话总结
    logger.info("生成对话总结")
    summary = self._generate_dialogue_summary(
      performances, messages, request_openai_func
    )

    # 将总结存入memory
    self._save_dialogue_summary(summary)

    # 对提取的事件进行去重
    logger.info("对提取的事件进行内部去重")
    deduplicated = self.deduplicate_events(performances)
    if len(deduplicated) < len(performances):
      logger.info(f"内部去重: {len(performances)} -> {len(deduplicated)} 条")

    # 与data.js中当前日期之后的数据合并去重
    if data_file:
      logger.info(f"与数据文件 {data_file} 合并去重")
      result = self._merge_with_data_file(deduplicated, data_file)
    else:
      result = deduplicated

    # 添加session，保留原文和提取结果
    self.add_session(texts, result)

    # 保存memory到磁盘
    self.save_memory()

    # 生成并输出brain报告
    brain_report = self.generate_report()
    logger.debug(f"Brain报告:\n{brain_report}")

    return result

  def _get_known_context(self) -> str:
    """获取已知信息的上下文"""
    lines = []

    # 已知公演类型
    performance_types = self.memory.get("performance_types", {})
    if performance_types:
      lines.append("公演类型：")
      for type_key, type_desc in performance_types.items():
        lines.append(f"  - {type_key}: {type_desc}")

    # 已知公演
    known = self.memory.get("known_performances", [])
    if known:
      lines.append("\n已知公演：")
      for perf in known[:15]:
        theme = perf.get("theme", "")
        team = perf.get("team", "")
        perf_type = perf.get("type", "regular")
        type_str = f" [{perf_type}]" if perf_type != "regular" else ""
        lines.append(f"  - {theme} - {team}{type_str}")

    # 已知团队别名
    team_aliases = self.memory.get("team_aliases", {})
    if team_aliases:
      lines.append("\n已知团队别名：")
      for standard, aliases in list(team_aliases.items())[:5]:
        if aliases:
          lines.append(f"  - {standard}: {', '.join(aliases)}")

    return "\n".join(lines)

  def _learn_performances(
    self,
    text: str,
    known_context: str,
    rules_text: str,
    messages: List[Dict],
    request_openai_func,
  ) -> tuple:
    """第一轮：提取公演主题和团队（含time/theme/team/type）"""
    # 添加用户消息
    messages.append(
      {
        "role": "user",
        "content": f"""**提取规则：**
        {rules_text}

        **Brain记忆信息：**
        {known_context}

        请从以下微博原文中提取所有与SNH48及其姐妹团体相关的公演信息。

        请提取每条公演的以下字段：
        1. time：演出时间，格式 YYYY/MM/DD HH:MM
        2. theme：公演主题名称（保留书名号《》）
        3. team：演出团队（如TEAM SII、GNZ48、TEAM G等。个人公演格式为团体名-成员名）
        4. type：公演类型（regular/special/new_star/graduation/concert/custom）

        公演类型说明：
        - regular: 常规公演
        - special: 特别公演（如专场、纪念公演等）
        - new_star: 新星闪耀计划
        - graduation: 毕业公演
        - concert: 演唱会
        - custom: 个人定制公演

        注意：
        - 只提取公演、演唱会信息，忽略见面会、握手会、直播等
        - 遵守提取规则中的所有要求
        - 生日公演/MVP公演/首演环节是团队公演的一部分，不应单独提取

        示例输出：
        [
          {{"time": "2026/01/08 19:30", "theme": "《Fire X》", "team": "TEAM X", "type": "regular"}},
          {{"time": "2026/01/07 19:30", "theme": "《B•RISE 梦之门》", "team": "SNH48-新生队", "type": "regular"}}
        ]

        微博原文：
        {text}""",
      }
    )

    try:
      result = request_openai_func(messages)
      if result:
        # 清理JSON字符串
        result = result.strip()
        if result.startswith("```json"):
          result = result[7:]
        if result.endswith("```"):
          result = result[:-3]
        result = result.strip()

        # 添加助手回复到对话历史
        messages.append({"role": "assistant", "content": result})

        data = json.loads(result)

        # 如果返回的是数组，直接使用
        if isinstance(data, list):
          performances = data
        else:
          performances = data.get("performances", [])

        # 学习公演信息
        for perf in performances:
          theme = perf.get("theme", "")
          team = perf.get("team", "")
          perf_type = perf.get("type", "regular")
          if theme and team:
            # 检查是否已存在
            known = self.memory.get("known_performances", [])
            exists = any(p.get("theme") == theme for p in known)
            if not exists:
              self.memory.setdefault("known_performances", []).append(
                {
                  "theme": theme,
                  "team": team,
                  "type": perf_type,
                  "aliases": [],
                }
              )
              logger.info(f"学习到新公演: {theme} - {team} [{perf_type}]")

        return performances, messages
    except Exception as e:
      logger.error(f"第一轮学习失败: {e}")

    return [], messages

  def _learn_team_aliases(
    self,
    text: str,
    performances: List[Dict],
    messages: List[Dict],
    request_openai_func,
  ) -> List[Dict]:
    """第二轮：基于第一轮结果，识别团队别名"""
    # 构建第一轮结果摘要
    perf_summary = "\n".join(
      [f"- {p.get('theme', '')} - {p.get('team', '')}" for p in performances[:10]]
    )

    # 添加用户消息
    messages.append(
      {
        "role": "user",
        "content": f"""基于刚才提取的公演信息：
        {perf_summary}

        请从微博原文中识别这些团队的别名或简称。

        常见的团队标准名称：
        - SNH48, GNZ48, BEJ48, CKG48, CGT48, SHY48
        - TEAM SII, TEAM NII, TEAM HII, TEAM X, TEAM G, TEAM NIII, TEAM Z等

        请识别：
        1. 团队的简称或别名（如SNH是SNH48的别名）
        2. 团队的其他表示方式

        请以JSON格式返回，key是标准名称，value是别名数组。
        示例：{{"SNH48": ["SNH", "SNH48 GROUP"], "GNZ48": ["GNZ"]}}

        只返回JSON格式，不要其他文字。""",
      }
    )

    try:
      result = request_openai_func(messages)
      if result:
        result = result.strip()
        if result.startswith("```json"):
          result = result[7:]
        if result.endswith("```"):
          result = result[:-3]
        result = result.strip()

        # 添加助手回复到对话历史
        messages.append({"role": "assistant", "content": result})

        data = json.loads(result)

        # 学习团队别名
        for standard, aliases in data.items():
          existing = self.memory.get("team_aliases", {}).get(standard, [])
          for alias in aliases:
            if alias not in existing:
              self.memory.setdefault("team_aliases", {}).setdefault(
                standard, []
              ).append(alias)
              logger.info(f"学习到团队别名: {alias} -> {standard}")
    except Exception as e:
      logger.error(f"第二轮学习失败: {e}")

    return messages

  def _learn_theme_normalization(
    self,
    text: str,
    performances: List[Dict],
    messages: List[Dict],
    request_openai_func,
  ):
    """第三轮：基于前两轮结果，识别主题变体和规范化规则"""
    # 构建第一轮结果摘要
    perf_summary = "\n".join(
      [f"- {p.get('theme', '')} - {p.get('team', '')}" for p in performances[:10]]
    )

    # 添加用户消息
    messages.append(
      {
        "role": "user",
        "content": f"""基于刚才提取的公演信息：
        {perf_summary}

        请从微博原文中识别这些公演主题的变体和规范化规则。

        需要识别的变体类型：
        1. 版本号变体：如《瑶光之迹[2.0]》是《瑶光之迹》的变体
        2. 特殊标记变体：如《没有我的世界(uN_v3rse)》是《没有我的世界》的变体
        3. 前缀变体：如《偶像研究计划H组-心的旅程》是《心的旅程》的变体

        请以JSON格式返回，key是原始变体，value是规范化后的主题（不含书名号）。
        示例：{{"瑶光之迹[2.0]": "瑶光之迹", "没有我的世界(uN_v3rse)": "没有我的世界"}}

        只返回JSON格式，不要其他文字。""",
      }
    )

    try:
      result = request_openai_func(messages)
      if result:
        result = result.strip()
        if result.startswith("```json"):
          result = result[7:]
        if result.endswith("```"):
          result = result[:-3]
        result = result.strip()

        # 添加助手回复到对话历史
        messages.append({"role": "assistant", "content": result})

        data = json.loads(result)

        # 学习主题规范化
        for original, normalized in data.items():
          self.memory.setdefault("theme_normalization", {})[original] = normalized
          logger.info(f"学习到主题规范化: {original} -> {normalized}")
    except Exception as e:
      logger.error(f"第三轮学习失败: {e}")

    return messages

  def _learn_deduplication_rules(
    self,
    text: str,
    performances: List[Dict],
    messages: List[Dict],
    request_openai_func,
  ):
    """第四轮：基于前三轮结果，分析去重规则和成员团队对应关系"""
    # 构建第一轮结果摘要
    perf_summary = "\n".join(
      [f"- {p.get('theme', '')} - {p.get('team', '')}" for p in performances[:10]]
    )

    # 从原文中提取相关片段（截取前后文，帮助AI理解成员和团队的关联）
    text_snippet = text[:2000] if len(text) > 2000 else text

    # 添加用户消息
    messages.append(
      {
        "role": "user",
        "content": f"""基于刚才提取的公演信息以及微博原文，分析成员与团队的对应关系。

        提取的公演信息：
        {perf_summary}

        微博原文片段：
        {text_snippet}

        请分析以下内容：

        1. 成员与团队的对应关系（从原文中推断）：
          - 从提取结果中"团队名-成员名"格式提取成员姓名
          - 从原文中分析：当某一团队公演下方列出"首演阵容""参演成员""演出阵容"等名单时，名单中的成员属于该团队
          - 示例1：原文"TEAM HII焕新公演《赫兹共振》 @SNH48-梁怀方 生日公演" → 梁怀方属于TEAM HII
          - 示例2：原文"TEAM SII全新原创公演《INTO THE LIGHT》 首演阵容：@SNH48-刘增艳 @SNH48-周童玥 @SNH48-芦馨怡 @SNH48-盛乐 @SNH48-李婷" → 刘增艳、周童玥、芦馨怡、盛乐、李婷都属于TEAM SII
          - 示例3：原文"TEAM NII焕新公演《Nice to meet you II》 @SNH48-柏欣妤 季度MVP公演" → 柏欣妤属于TEAM NII

        2. 主题规范化规则：
          - 如果主题不包含书名号《》，则自动添加《》
          - 如果主题已包含书名号，保持原样

        3. 重复判断标准：
          - 日期相同 + 主题相同 + 团队相同（或成员属于该团队）视为重复
          - 成员个人公演与团队公演主题相同时视为重复

        4. 非重复情况：
          - 日期不同的相同主题
          - 主题相同但团队不同（且成员不属于该团队）

        请以JSON格式返回，包含以下字段：
        - member_team_mapping: 成员与团队的对应关系映射（key为成员名，value为团队标准名称）
        - duplicate_rules: 去重规则列表
        - examples: 重复和非重复的示例

        只返回JSON格式，不要其他文字。""",
      }
    )

    try:
      result = request_openai_func(messages)
      if result:
        result = result.strip()
        if result.startswith("```json"):
          result = result[7:]
        if result.endswith("```"):
          result = result[:-3]
        result = result.strip()

        # 添加助手回复到对话历史
        messages.append({"role": "assistant", "content": result})

        data = json.loads(result)

        # 学习成员与团队的对应关系
        member_team_mapping = data.get("member_team_mapping", {})
        for member, team in member_team_mapping.items():
          self.memory.setdefault("member_team_mapping", {})[member] = team
          logger.info(f"学习到成员团队对应关系: {member} -> {team}")

        # 学习去重规则（合并而非覆盖，保留手动添加的examples等字段）
        new_rules = data.get("duplicate_rules", [])
        if new_rules:
          existing = self.memory.get("duplicate_rules", {})
          existing["rules"] = new_rules
          existing["updated_at"] = datetime.now().isoformat()
          self.memory["duplicate_rules"] = existing
          logger.info(f"学习到去重规则: {len(new_rules)}条")
    except Exception as e:
      logger.error(f"第四轮学习失败: {e}")

  def _generate_dialogue_summary(
    self, performances: List[Dict], messages: List[Dict], request_openai_func
  ) -> Dict[str, Any]:
    """生成对话总结"""
    # 构建第一轮结果摘要
    perf_summary = "\n".join(
      [f"- {p.get('theme', '')} - {p.get('team', '')}" for p in performances[:10]]
    )

    # 添加用户消息
    messages.append(
      {
        "role": "user",
        "content": f"""基于刚才的多轮对话，请生成一个总结，包括：

        1. 提取的公演信息：
        {perf_summary}

        2. 学习到的团队别名
        3. 学习到的主题规范化规则
        4. 学习到的去重规则

        请以JSON格式返回，包含以下字段：
        - summary: 总结文本
        - new_performances: 新学习的公演数量
        - new_aliases: 新学习的别名数量
        - new_normalizations: 新学习的规范化规则数量
        - key_findings: 关键发现列表

        只返回JSON格式，不要其他文字。""",
      }
    )

    try:
      result = request_openai_func(messages)
      if result:
        result = result.strip()
        if result.startswith("```json"):
          result = result[7:]
        if result.endswith("```"):
          result = result[:-3]
        result = result.strip()

        # 添加助手回复到对话历史
        messages.append({"role": "assistant", "content": result})

        data = json.loads(result)
        return data
    except Exception as e:
      logger.error(f"生成对话总结失败: {e}")

    return {}

  def _save_dialogue_summary(self, summary: Dict[str, Any]):
    """将对话总结存入memory"""
    if not summary:
      return

    # 添加时间戳
    summary["timestamp"] = datetime.now().isoformat()

    # 存入dialogue_summaries
    self.memory.setdefault("dialogue_summaries", []).append(summary)

    # 只保留最近20个总结
    if len(self.memory["dialogue_summaries"]) > 20:
      self.memory["dialogue_summaries"] = self.memory["dialogue_summaries"][-20:]

    logger.info(f"对话总结已保存: {summary.get('summary', '')[:100]}...")

  def should_exclude(self, text: str) -> bool:
    """判断文本是否包含应排除的关键词"""
    excluded = self.memory.get("excluded_keywords", [])
    for keyword in excluded:
      if keyword in text:
        return True
    return False

  def normalize_theme(self, theme: str) -> str:
    """规范化主题名称"""
    core_theme = theme.replace("《", "").replace("》", "").strip()

    normalization = self.memory.get("theme_normalization", {})
    if core_theme in normalization:
      return f"《{normalization[core_theme]}》"

    if not theme.startswith("《"):
      theme = f"《{theme}"
    if not theme.endswith("》"):
      theme = f"{theme}》"

    return theme

  def normalize_team(self, team: str) -> str:
    """规范化团队名称"""
    team_aliases = self.memory.get("team_aliases", {})

    for standard_name, aliases in team_aliases.items():
      if team == standard_name or team in aliases:
        return standard_name

    return team

  def is_duplicate(self, event1: Dict[str, str], event2: Dict[str, str]) -> bool:
    """判断两条记录是否重复，从memory.json读取去重逻辑"""
    # 获取去重规则配置
    duplicate_rules = self.memory.get("duplicate_rules", {})

    # 检查是否启用去重
    if not duplicate_rules.get("duplicate判断", {}).get("enabled", True):
      return False

    time1 = event1.get("time", "")
    time2 = event2.get("time", "")
    theme1 = self.normalize_theme(event1.get("theme", ""))
    theme2 = self.normalize_theme(event2.get("theme", ""))
    team1 = self.normalize_team(event1.get("team", ""))
    team2 = self.normalize_team(event2.get("team", ""))

    # 提取日期部分
    date1 = time1.split(" ")[0] if " " in time1 else time1
    date2 = time2.split(" ")[0] if " " in time2 else time2

    # 日期不同不是重复
    if date1 != date2:
      return False

    # 提取核心主题
    core1 = theme1.replace("《", "").replace("》", "").strip()
    core2 = theme2.replace("《", "").replace("》", "").strip()

    # 获取成员与团队的对应关系
    member_team_mapping = self.memory.get("member_team_mapping", {})

    # 检查是否是成员个人公演与团队公演的关系
    def get_real_team(team_str):
      """获取真实的团队名称，处理成员个人公演的情况"""
      # 检查是否是"团体名-成员名"格式
      if "-" in team_str:
        parts = team_str.split("-", 1)
        member_name = parts[1]
        # 查找成员对应的团队
        if member_name in member_team_mapping:
          return member_team_mapping[member_name]
      return team_str

    real_team1 = get_real_team(team1)
    real_team2 = get_real_team(team2)

    # 完全相同主题
    if core1 == core2:
      # 团队相同或一个是另一个的子集
      if (
        real_team1 == real_team2 or real_team1 in real_team2 or real_team2 in real_team1
      ):
        return True
      # 检查成员与团队的对应关系
      if team1 != real_team1 or team2 != real_team2:
        # 如果一个是成员个人公演，一个是团队公演，且成员属于该团队
        if real_team1 == real_team2:
          return True

    # 主题包含关系（如《心的旅程》和《偶像研究计划H组-心的旅程》）
    if core1 in core2 or core2 in core1:
      # 团队相同或兼容
      if (
        real_team1 == real_team2 or real_team1 in real_team2 or real_team2 in real_team1
      ):
        return True
      # 检查成员与团队的对应关系
      if team1 != real_team1 or team2 != real_team2:
        if real_team1 == real_team2:
          return True

    # 检查个人环节主题（季度MVP公演/生日公演/MVP公演）与团队公演的关系
    personal_themes = ["季度MVP公演", "生日公演", "MVP公演", "TOP16主题生日公演"]
    one_is_personal = core1 in personal_themes or core2 in personal_themes
    if one_is_personal and date1 == date2:
      # 如果一个是个人环节，另一个是团队公演，且成员属于该团队
      for perf_core, event_team, real_team in [
        (core1, team1, real_team1),
        (core2, team2, real_team2),
      ]:
        other_real_team = real_team2 if perf_core == core1 else real_team1
        if perf_core in personal_themes:
          # 个人环节的team应该是"团体名-成员名"格式
          if "-" in event_team:
            member_name = event_team.split("-", 1)[1]
            if member_name in member_team_mapping:
              member_team = member_team_mapping[member_name]
              # 成员所属团队与另一个事件的团队一致
              if (
                member_team == other_real_team
                or other_real_team in member_team
                or member_team in other_real_team
              ):
                return True

    # 检查已知公演的别名
    known_performances = self.memory.get("known_performances", [])
    for perf in known_performances:
      perf_theme = perf.get("theme", "").replace("《", "").replace("》", "")
      perf_aliases = perf.get("aliases", [])

      # 检查两个主题是否都匹配同一个已知公演
      match1 = core1 == perf_theme or core1 in perf_aliases
      match2 = core2 == perf_theme or core2 in perf_aliases

      if match1 and match2:
        perf_team = perf.get("team", "")
        if (
          real_team1 == real_team2 or real_team1 == perf_team or real_team2 == perf_team
        ):
          return True

    return False

  def deduplicate_events(self, events: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """对事件列表进行去重"""
    if not events:
      return []

    result = []
    for event in events:
      is_dup = False
      for existing in result:
        if self.is_duplicate(event, existing):
          is_dup = True
          logger.debug(f"发现重复: {event} 与 {existing}")
          break

      if not is_dup:
        result.append(event)

    return result

  def filter_events(self, events: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """过滤事件，排除非公演信息"""
    result = []
    for event in events:
      theme = event.get("theme", "")
      team = event.get("team", "")
      combined = f"{theme} {team}"

      if not self.should_exclude(combined):
        result.append(event)
      else:
        logger.debug(f"排除非公演信息: {event}")

    return result

  def get_extraction_context(self) -> str:
    """获取用于提取的上下文信息"""
    lines = []

    # 添加session上下文
    session_context = self.get_session_context(3)
    if session_context:
      lines.append(session_context)

    # 添加已知公演
    lines.append("\n【已知公演信息】")
    known = self.memory.get("known_performances", [])
    if known:
      for perf in known[:20]:
        theme = perf.get("theme", "")
        team = perf.get("team", "")
        aliases = perf.get("aliases", [])
        note = perf.get("note", "")
        alias_str = f" (别名: {', '.join(aliases)})" if aliases else ""
        note_str = f" [{note}]" if note else ""
        lines.append(f"- {theme} - {team}{alias_str}{note_str}")

    # 添加排除关键词
    excluded = self.memory.get("excluded_keywords", [])
    if excluded:
      lines.append("\n【排除关键词】")
      lines.append(f"以下关键词出现时应排除: {', '.join(excluded)}")

    # 添加主题规范化规则
    normalization = self.memory.get("theme_normalization", {})
    if normalization:
      lines.append("\n【主题规范化规则】")
      for original, normalized in list(normalization.items())[:10]:
        lines.append(f"- {original} → {normalized}")

    # 添加成员与团队的对应关系
    member_team_mapping = self.memory.get("member_team_mapping", {})
    if member_team_mapping:
      lines.append("\n【成员与团队对应关系】")
      for member, team in member_team_mapping.items():
        lines.append(f"- {member} 属于 {team}")

    # 添加去重规则
    duplicate_rules = self.memory.get("duplicate_rules", {})
    if duplicate_rules:
      lines.append("\n【去重规则】")
      for rule_name, rule_config in duplicate_rules.items():
        if isinstance(rule_config, dict):
          rules_list = rule_config.get("rules", [])
          for rule_text in rules_list:
            lines.append(f"- [{rule_name}] {rule_text}")
        elif isinstance(rule_config, str) and rule_name != "description":
          lines.append(f"- [{rule_name}] {rule_config}")

    return "\n".join(lines)

  def get_extraction_rules(self) -> Dict[str, Any]:
    """获取提取规则"""
    return self.memory.get("extraction_rules", {})

  def generate_report(self) -> str:
    """生成brain报告"""
    sessions = self.memory.get("sessions", [])
    known = self.memory.get("known_performances", [])
    normalization = self.memory.get("theme_normalization", {})
    excluded = self.memory.get("excluded_keywords", [])

    report = f"""=== Brain Memory Report ===

    【Session数量】: {len(sessions)}
    【已知公演数量】: {len(known)}
    【规范化规则数量】: {len(normalization)}
    【排除关键词数量】: {len(excluded)}

    【最近Session】
    """
    for i, session in enumerate(sessions[-3:], 1):
      timestamp = session.get("timestamp", "")
      text_count = session.get("text_count", 0)
      event_count = session.get("event_count", 0)
      report += f"  {i}. {timestamp} - {text_count}条原文, {event_count}个事件\n"

    report += "\n【已知公演列表】\n"
    for perf in known[:10]:
      report += f"  - {perf.get('theme', '')} - {perf.get('team', '')}\n"

    if len(known) > 10:
      report += f"  ... 还有 {len(known) - 10} 个\n"

    report += "\n【主题规范化规则】\n"
    for original, normalized in list(normalization.items())[:5]:
      report += f"  - {original} → {normalized}\n"

    return report

  def _read_data_file(self, file_path: str) -> Optional[List[Dict]]:
    """读取data.js文件并解析JSON数据"""
    try:
      with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
      if "const eventData = " in content:
        start = content.find("[")
        end = content.rfind("];")
        if start != -1 and end != -1:
          return json.loads(content[start : end + 1])
    except Exception as e:
      logger.error(f"读取数据文件失败 {file_path}: {e}")
    return None

  def _write_data_file(self, data: List[Dict], file_path: str):
    """将数据写入data.js文件"""
    try:
      with open(file_path, "w", encoding="utf-8") as f:
        f.write("// data.js\n")
        f.write("const eventData = ")
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write(";\n")
    except Exception as e:
      logger.error(f"写入数据文件失败 {file_path}: {e}")

  def _sort_events_by_time(self, events: List[Dict]) -> List[Dict]:
    """按时间排序事件"""

    def sort_key(event):
      t = event.get("time", "")
      try:
        return datetime.strptime(t, "%Y/%m/%d %H:%M")
      except (ValueError, TypeError):
        return datetime.min

    return sorted(events, key=sort_key)

  def _merge_with_data_file(self, new_events: List[Dict], data_file: str) -> List[Dict]:
    """将新事件与data.js中当前日期之后的数据合并去重，写回文件"""
    data = self._read_data_file(data_file)
    if data is None:
      logger.warning("数据文件为空或不存在，仅写入新事件")
      self._write_data_file(new_events, data_file)
      return new_events

    current_date = datetime.now().strftime("%Y/%m/%d")

    # 按当前日期切分
    future_data = []
    past_data = []
    for item in data:
      item_date = (
        item.get("time", "").split(" ")[0]
        if " " in item.get("time", "")
        else item.get("time", "")
      )
      if item_date >= current_date:
        future_data.append(item)
      else:
        past_data.append(item)

    logger.info(f"data.js中当前日期({current_date})之后的数据: {len(future_data)}条")
    logger.info(f"data.js中当前日期之前的数据: {len(past_data)}条")

    # 合并新事件与未来数据，去重
    combined = future_data + new_events
    deduplicated = self.deduplicate_events(combined)
    new_count = max(0, len(deduplicated) - len(future_data))

    # 合并所有数据
    all_data = past_data + deduplicated
    all_data = self._sort_events_by_time(all_data)

    self._write_data_file(all_data, data_file)
    logger.info(f"数据已更新到{data_file}，新增{new_count}条，共{len(all_data)}条")

    # 返回去重后的新事件（用于后续展示）
    new_event_times = {
      (e.get("time", ""), e.get("theme", ""), e.get("team", "")) for e in new_events
    }
    result = [
      e
      for e in deduplicated
      if (e.get("time", ""), e.get("theme", ""), e.get("team", "")) in new_event_times
    ]
    return result
