from playwright.sync_api import Playwright, sync_playwright
from openai import OpenAI
from dotenv import load_dotenv
from dateutil import parser
import time
import json
import os
import logging
import requests
from datetime import datetime
from functools import cmp_to_key

load_dotenv() 

log_level = os.getenv("LOG_LEVEL", "INFO")
openai_api_key = os.getenv("OPENAI_API_KEY")
openai_api_base_url = os.getenv("OPENAI_API_BASE_URL")
openai_model = os.getenv("OPENAI_MODEL")
feishu_webhook_id = os.getenv("FEISHU_WEBHOOK_ID", "")
required_keywords_str = os.getenv("REQUIRED_KEYWORDS", "")
required_keywords = [keyword.strip() for keyword in required_keywords_str.split(",")] if required_keywords_str else []

# 配置日志
logging.basicConfig(
    level=getattr(logging, log_level.upper(), logging.INFO),
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

weibo_urls = [
  "https://weibo.com/u/2689280541", #  snh48
  "https://weibo.com/u/5676293287", #  bej48
  "https://weibo.com/u/5675361083", #  gnz48
  "https://weibo.com/u/6250843867", #  ckg48
  "https://weibo.com/u/7614913886"  #  cgt48
]

timestamp_template = "%a %b %d %H:%M:%S %z %Y" # Tue Dec 02 12:34:34 +0800 2025

time_range = 60 * 60 * 8

def get_team_index(team_str, sort_indexs):
  """通过模糊匹配获取team在排序列表中的索引"""
  team_upper = team_str.upper()
  for i, index_item in enumerate(sort_indexs):
    index = team_upper.find(index_item)
    if index != -1:  # 如果找到了匹配
      # 检查是否为完整的单词边界匹配
      start_ok = (index == 0) or (not team_upper[index - 1].isalnum())  # 前面不是字母数字
      end_ok = (index + len(index_item) == len(team_upper)) or (not team_upper[index + len(index_item)].isalnum())  # 后面不是字母数字
      if start_ok and end_ok:
          return i
  for i, index_item in enumerate(sort_indexs):
    index = team_upper.find(index_item)
    if index != -1:  # 如果找到了匹配
      return i
  return len(sort_indexs)  # 如果没找到，放到最后

def sort_custom_key(item1, item2):
  #判断是否有time字段
  if "time" not in item1 or "time" not in item2:
    return 0
  t1 = datetime.strptime(item1['time'], '%Y/%m/%d %H:%M')
  t2 = datetime.strptime(item2['time'], '%Y/%m/%d %H:%M')
  if t1 > t2:
    return 1
  elif t1 < t2:
    return -1
  else:
    if "team" in item1 and "team" in item2:
      sort_indexs = ['SII', 'NII', 'HII', 'X', 'XII', 'G', 'NIII', 'Z', 'B', 'E', 'J', 'C', 'K', 'CII', 'GII', 'SIII', 'HIII',
                     'SNH48', 'SNH', 'GNZ48', 'GNZ', 'BEJ48', 'BEJ', 'CKG48', 'CKG', 'CGT48', 'CGT', 'SHY48', 'SHY']
      team_index1 = get_team_index(item1['team'], sort_indexs)
      team_index2 = get_team_index(item2['team'], sort_indexs)
      if team_index1 > team_index2:
        return 1
      elif team_index1 < team_index2:
        return -1
    return 0

def format_time_str_zh(time_str):
  [d, t] = time_str.split(' ')
  [year, month, day] = d.split('/')
  return f"{year}年{month}月{day}日 {t}"

def read_json_from_file(file_name):
  try:
    with open(file_name, "r", encoding="utf-8") as f:
      content = f.read()
      if "const eventData = " in content:
        start = content.find("[")
        end = content.rfind("];")
        if start != -1 and end != -1:
          json_str = content[start:end+1]
          return json_str
  except Exception as e:
    logger.error(f"读取文件{file_name}时出错: {e}")
    return None

def write_to_file(data, file_name):
  if not data:
    logger.warning("没有数据写入文件")
    return
  
  try:
    new_event_data = json.loads(data)
    # 写入更新后的data.js文件
    with open(file_name, "w", encoding="utf-8") as f:
      f.write("// data.js\n")
      f.write("const eventData = ")
      json.dump(new_event_data, f, ensure_ascii=False, indent=2)
      f.write(";\n")
  except json.JSONDecodeError as e:
    logger.error(f"JSON解析错误: {e}\n JSON数据: \n{data}\n")
  except Exception as e:
    logger.error(f"写入文件时发生错误: {e}")

def smart_scroll_to_bottom(page, scroll_step=800, max_attempts=30, stable_threshold=3):
  """智能滚动到底部：结合滚轮、高度判断和网络监听"""
  last_height = page.evaluate("document.documentElement.scrollHeight")
  stable_count = 0
  
  for i in range(max_attempts):
    page.mouse.wheel(0, scroll_step)
    page.wait_for_timeout(5000)
    new_height = page.evaluate("document.documentElement.scrollHeight")
    
    if new_height == last_height:
      stable_count += 1
      if stable_count >= stable_threshold:
        logger.debug(f"连续{stable_threshold}次滚动后页面高度未变化，认为已到底部。")
        break
    else:
      stable_count = 0 # 高度变化，重置计数
      last_height = new_height  

    logger.debug(f"第{i+1}次滚动，页面高度: {new_height}")   

  logger.debug("滚动结束。")

def smart_scroll_to_bottom_use_phone(page, scroll_step=800):
  """智能滚动到底部：结合滚轮、高度判断和网络监听"""
  last_height = page.evaluate("window.lastHight ? window.lastHight : 0")
  new_height = page.evaluate("""() => {
    app = document.getElementById("app");
    first_div = app.children[0];
    newHeight = first_div.children[0].scrollHeight
    window.lastHight = newHeight;
    return newHeight;            
  }""")
  for i in range(int((new_height - last_height)/ scroll_step)):
    page.mouse.wheel(0, scroll_step)
    page.wait_for_timeout(5000)
    logger.debug(f"第{i+1}次滚动，页面高度: {new_height}")

def wait_for_scroll_to_bottom(page, timeout=30000):
  try:
    page.wait_for_function("""() => {
      const stableFrames = 5; // 连续稳定帧数
      let lastHeight = document.documentElement.scrollHeight;
      let framesUnchanged = 0;
      
      return new Promise((resolve) => {
        const checkHeight = () => {
          const currentHeight = document.documentElement.scrollHeight;
          if (currentHeight === lastHeight) {
            framesUnchanged++;
          } else {
            framesUnchanged = 0;
            lastHeight = currentHeight;
          }
          
          if (framesUnchanged >= stableFrames) {
            resolve(true);
          } else {
            setTimeout(checkHeight, 6000); // 每2s检查一次  大于page.wait_for_timeout(5000)否则报错
          }
        };
        checkHeight();
      });
    }""", timeout=timeout)
  except Exception as e:
    logger.error(f"等待滚动到底部时出错: {e}")

def wait_for_scroll_to_bottom_use_phone(page, timeout=30000):
  try:
    page.wait_for_function("""() => {
      const stableFrames = 10; // 连续稳定帧数
      let lastHeight = window.lastHight;
      let framesUnchanged = 0;
      
      return new Promise((resolve) => {
        const checkHeight = () => {
          const currentHeight = window.lastHight;
          if (currentHeight === lastHeight) {
            framesUnchanged++;
          } else {
            framesUnchanged = 0;
            lastHeight = currentHeight;
          }
          
          if (framesUnchanged >= stableFrames) {
            resolve(true);
          } else {
            setTimeout(checkHeight, 6000); // 每2s检查一次  大于page.wait_for_timeout(5000)否则报错
          }
        };
        checkHeight();
      });
    }""", timeout=timeout)
  except Exception as e:
    logger.error(f"等待滚动到底部时出错: {e}")

def request_openai(messages):
  try:
    client = OpenAI(
      api_key=openai_api_key,
      base_url=openai_api_base_url,
    )

    completion = client.chat.completions.create(
      model=openai_model,
      messages=messages,
      temperature=0.3,  # 降低随机性，提高一致性
      response_format={"type": "json_object"}  # 确保响应为JSON格式
    )
    json_str = completion.choices[0].message.content
    if "```json" in json_str:
      json_str = json_str.split("```json")[1].split("```")[0]
    elif "```" in json_str:
      parts = json_str.split("```")
      if len(parts) >= 3:
        json_str = parts[1]
    return json_str
  except Exception as e:
    logger.error(f"OpenAI API调用失败: {e}")
    return None

def update_data(result, file_path):
  data_json = read_json_from_file(file_path)
  if not data_json:
    logger.warning("data.js文件为空或不存在")
    return None
  data_json = json.loads(data_json)
  result_json = json.loads(result)
  seen_times = {parser.parse(item.get('time', '')) for item in result_json}
  data_json_clip = []
  data_json_rest = []
  for item in data_json:
      time = parser.parse(item.get('time', ''))
      if time in seen_times:
          data_json_clip.append(item)
      else:
          data_json_rest.append(item)
  result_json.extend(data_json_clip)
  result_json = [{**item, 'time_zh': format_time_str_zh(item['time'])} 
                  for item in result_json]
  messages = [
    {
      "role": "system",
      "content": """你是一个专业的数据去重助手，专门对演出信息进行智能去重处理。请严格按照以下规则处理输入数据，并只输出严格的JSON格式，不包含任何其他文字。\n\n
                  **去重规则：**\n
                    1. **主题规范化**：对所有`theme`字段进行标准化处理：\n
                      - 如果主题不包含书名号《》，则自动添加《》\n 
                      - 如果主题已包含书名号，保持原样\n
                      - 示例：\"B•RISE 梦之门\" → \"《B•RISE 梦之门》\"，\"《Fire X》\"保持不变\n\n
                    2. **场次划分规则**（用于判断是否同一场次）：\n
                      - **午场**：12:00 至 17:00 之间的演出（包含12:00，不包含17:00）\n
                      - **晚场**：17:00 至 22:00 之间的演出（包含17:00，不包含22:00）\n
                      - **其他场次**：不在上述时间段内的演出，按实际时间单独计算场次\n\n
                    3. **重复判断标准**：两条记录被视为重复需同时满足以下条件：\n
                      a) **日期相同**：从`time`字段提取的日期部分（YYYY/MM/DD）相同\n
                      b) **场次相同**：根据上述场次划分规则，两条记录属于同一场次\n
                      c) **标准化主题相同**：经过上述规范化处理后的`theme`相同\n
                      d) **团队相同**：`team`字段内容相同（忽略大小写差异）\n\n
                    4. **非重复情况**：以下情况不视为重复，应全部保留：\n
                      - 日期不同的相同主题（如2025/01/07和2025/01/08都有《同一主题》）\n
                      - 主题相同但团队不同（如《同一主题》由TEAM SII和TEAM NII分别演出）\n
                      - 团队相同但主题不同\n\n
                    5. **去重处理逻辑**：\n
                      - 按输入顺序遍历所有记录\n
                      - 当发现重复记录时，保留首次出现的记录，移除后续重复记录\n
                      - 保持非重复记录的原始顺序\n\n
                  **输出要求：**\n- 输出必须是有效的JSON数组格式\n
                    - 包含去重后的所有记录，保持原始结构\n- 每条记录保持原始的`time`、`theme`、`team`三个字段\n
                    - `theme`字段保持规范化后的形式（带书名号）\n
                    - 不包含任何解释性文字、注释或格式标记"""
    },
    {
      "role": "user",
      "content": f"请对以下演出信息进行去重处理，严格遵守上述规则，只输出去重后的JSON数组：\n\n { json.dumps(result_json, ensure_ascii=False) }"
    }
  ]
  filter_result_data = request_openai(messages)
  filter_result_data_json = json.loads(filter_result_data)
  data_json_rest.extend(filter_result_data_json)
  data_json_rest.sort(key=cmp_to_key(sort_custom_key))
  data_json_all = [
      {key: value for key, value in d.items() if key != 'time_zh'}
      for d in data_json_rest
  ]
  write_to_file(json.dumps(data_json_all, ensure_ascii=False), file_path)
  logger.info(f"\n数据已成功更新到data.js文件，新增{len(data_json) - len(data_json_rest)}条记录")
  logger.info(f"总共有{len(data_json_rest)}条记录")

def get_weibo_mblog_by_playwright(playwright: Playwright, url: str) -> list:
  # 创建浏览器
  browser = playwright.chromium.launch(headless=True)
  content = browser.new_context()
  page = content.new_page()

  mymblog_statuses_flag = True
  blog_list = []
  def handle_response(response):
    try:
      # 筛选接口，例如包含"/api/data"的URL
      if "/ajax/statuses/mymblog" in response.url:
        logger.debug(f"捕获到响应 URL: {response.url}")
        logger.debug(f"状态码: {response.status}")
        if response.status != 200:
          logger.warning(f"/ajax/statuses/mymblog 接口请求失败，状态码: {response.status}")
          page.evaluate("() => window['mymblog_statuses_flag'] = false")
          return
        response_json = response.json()
        if 'data' in response_json and 'list' in response_json['data']:
          blog_list.extend(response_json['data']['list'])
          if blog_list:
            end_time_str = blog_list[-1].get('created_at', '')
            if end_time_str.strip():
              end_time = time.mktime(time.strptime(end_time_str, timestamp_template))
              logger.debug(f"最新时间: {end_time_str}")
              if end_time > time.time() - time_range:  # 7 天
                smart_scroll_to_bottom(page)
        else:
          logger.error(f"响应中缺少预期的数据结构: {'data' if 'data' in response_json else 'list'}")
    except Exception as e:
      logger.error(f"handle_response函数处理响应时出错: {e}")

  page.on("response", handle_response)
  page.goto(url)
  page.wait_for_load_state('networkidle')# 等待内容加载
  wait_for_scroll_to_bottom(page, timeout=1000 * 60 * 10)
  mymblog_statuses_flag = page.evaluate("window.mymblog_statuses_flag")
  page.close()
  content.close()
  browser.close()
  if mymblog_statuses_flag == False:
    return None
  return blog_list

def get_weibo_mblog_by_playwright_use_phone(playwright: Playwright, url: str) -> list:
  # 创建浏览器
  iphone_12 = playwright.devices['iPhone 12']
  browser = playwright.chromium.launch(headless=True)
  content = browser.new_context(**iphone_12)
  page = content.new_page()

  blog_list = []
  mymblog_statuses_flag = True
  def handle_response(response):
    try:
      # 筛选接口，例如包含"/api/data"的URL
      if "m.weibo.cn/api/container/getIndex" in response.url:
        logger.debug(f"捕获到响应 URL: {response.url}")
        logger.debug(f"状态码: {response.status}")
        if response.status != 200:
          logger.warning(f"m.weibo.cn/api/container/getIndex 接口请求失败，状态码: {response.status}")
          page.evaluate("() => window['mymblog_statuses_flag'] = false")
          return
        response_json = response.json()
        if 'data' in response_json and 'cards' in response_json['data']:
          for card in response_json['data']['cards']:
            if 'mblog' in card:
              mblog = card['mblog']
              blog_list.append(mblog)
          if blog_list:
            end_time_str = blog_list[-1].get('created_at', '')
            if end_time_str.strip():
              end_time = time.mktime(time.strptime(end_time_str, timestamp_template))
              logger.debug(f"weibo最新时间: {end_time_str}")
              if end_time > time.time() - time_range:  # 7 天
                smart_scroll_to_bottom_use_phone(page)
        else:
          logger.error(f"响应中缺少预期的数据结构: {'data' if 'data' in response_json else 'cards'}")
    except Exception as e:
      logger.error(f"handle_response函数处理响应时出错: {e}")
  
  page.on("response", handle_response)
  page.goto(url)
  page.wait_for_load_state('networkidle')
  wait_for_scroll_to_bottom_use_phone(page, timeout=1000 * 60 * 10)
  mymblog_statuses_flag = page.evaluate("window.mymblog_statuses_flag")
  page.close()
  content.close()
  browser.close()
  if mymblog_statuses_flag == False:
    return None
  return blog_list

def get_weibo_mblog_detail(playwright: Playwright, url: str) -> list:
  browser = playwright.chromium.launch(headless=True)
  content = browser.new_context()
  page = content.new_page()
  mblogs = []
  def handle_response(response):
      try:
        if "/ajax/statuses/show" in response.url:
          logger.debug(f"捕获到响应 URL: {response.url}")
          logger.debug(f"状态码: {response.status}")
          try:
            mblog = response.json()
            mblogs.append(mblog)
            if "retweeted_status" in mblog:
              mblogs.append(mblog["retweeted_status"])
          except Exception as e:
            logger.error(f"状态码: {response.status}")
            logger.error(response.body())
            logger.error(f"解析微博详情时出错: {e}")
      except Exception as e:
        logger.error(f"handle_response函数处理响应时出错: {e}")
  page.on("response", handle_response)
  page.goto(url)
  page.wait_for_load_state('networkidle')
  page.wait_for_timeout(10000)
  page.close()
  content.close()
  browser.close()
  return mblogs

def send_feishu_message(data, webhook_id):
  try: 
    url = f"https://open.feishu.cn/open-apis/bot/v2/hook/{webhook_id}"
    # 设置请求头
    headers = {
        'Content-Type': 'application/json'
    }
    
    # 发送POST请求
    response = requests.post(url, json=data, headers=headers)
    
    # 检查响应状态
    if response.status_code == 200:
      logger.info(f"飞书消息发送成功: {response.json()}")
    else:
      logger.error(f"飞书消息发送失败，状态码: {response.status_code}, 响应: {response.text}")
  except Exception as e:
    logger.error(f"飞书消息发送失败: {e}")

def send_feishu_card_content(json_data):
  if not feishu_webhook_id:
    return
  card_fields = []
  for item in json_data:
    time = item["time"]
    theme = item["theme"]
    team = item["team"]
    if required_keywords and not any(keyword in team for keyword in required_keywords):
      continue
    card_fields.append({
      "is_short": True, # True为半宽，False为全宽。通过组合可模拟行。
      "text": {
        "tag": "lark_md",
        "content": "**📅**" + time + "\n**📝**" + theme + "\n**👥**" + team
      }
    })
    card_fields.append({
      "tag": "hr"
    })
  if not card_fields:
    return
  card_content = {
    "msg_type": "interactive", # 消息类型为交互式卡片
    "card": {
      "elements": [{
        "tag": "div",
        "fields": card_fields[:len(card_fields) - 1]
      }],
      "header": { # 可选的卡片标题
        "template": "blue",
        "title": {
          "tag": "plain_text",
          "content": "演出日程提醒"
        }
      }
    }
  }

  send_feishu_message(card_content, feishu_webhook_id)

# 创建浏览器
def run (playwright: Playwright) -> None:
  try:
    mblogs = []
    for url in weibo_urls:
      try:
        # 页面打开指定网址
        logger.debug(f"正在访问: {url}")
        is_use_phone = False
        blog_list = get_weibo_mblog_by_playwright(playwright, url)
        if not blog_list:
          url = url.replace("weibo.com", "m.weibo.com")
          blog_list = get_weibo_mblog_by_playwright_use_phone(playwright, url)
          is_use_phone = True
          if not blog_list:
            continue
        for item in blog_list:
          try:
            created_at = item.get('created_at', '')
            if not created_at:
              continue

            t = time.mktime(time.strptime(created_at, timestamp_template))
            if t < time.time() - time_range: # 7 天
              continue
            
            mblog_url = ""
            if is_use_phone:
              mblogid = item.get('bid', '')
              user = item.get('user', {})
              user_idstr = user.get('id', '') if user else ''
              mblog_url = f"https://weibo.com/{user_idstr}/{mblogid}"
            else:
              mblogid = item.get('mblogid', '')
              user = item.get('user', {})
              user_idstr = user.get('idstr', '') if user else ''
              mblog_url = f"https://weibo.com/{user_idstr}/{mblogid}"
            
            logger.debug(f"访问微博详情: {mblog_url}")
            mblogs.extend(get_weibo_mblog_detail(playwright, mblog_url))
          except Exception as e:
            logger.error(f"处理博客项时出错: {e}")
      except Exception as e:
        logger.error(f"处理URL {url} 时出错: {e}")
        continue

    texts = []
    for item in mblogs:
      try:
        text_raw = item.get('text_raw', '')
        created_at = item.get('created_at', '')
        
        if not text_raw or not created_at:
          continue
        
        t = time.mktime(time.strptime(created_at, timestamp_template))
        if t > time.time() - time_range: # 7 天
          texts.append(text_raw)
      except Exception as e:
        logger.error(f"处理微博内容时出错: {e}\n 微博内容: \n{text_raw}\n")

    if not texts:
      logger.warning("没有收集到任何文本内容")
      return
    current_year = time.localtime(time.time()).tm_year
    current_month = time.localtime(time.time()).tm_mon + 1

    content = [
      {
        "role": "system",
        "content": """你是一个专业的数据提取助手，专门从文本中提取SNH48及其姐妹团体（GNZ48、BEJ48、CKG48、SHY48、CGT48）的公演、演唱会和运动会的时间信息。
                    你的唯一任务是输出严格的JSON数组格式，不包含任何其他文字、解释或格式标记。"""
      },
      {
        "role": "user",
        "content": f"""请从以下文本中提取所有购票信息，并整理为严格的JSON数组格式。\n\n
                    **提取规则：**\n1. **范围限制**：仅提取**公演、演唱会、运动会**的信息。见面会、握手会、足球赛、线上直播等其他活动一律忽略。\n
                    2. **团体限制**：仅处理以下团体：SNH48、GNZ48、BEJ48、CKG48、SHY48、CGT48。其他任何邀请演出均不统计。\n
                    3. **输出格式**：输出必须是一个JSON数组，每个对象包含且仅包含三个字段：`time`、`theme`、`team`。\n
                    4. **字段规范**：\n   - `time`：格式必须为 **`YYYY/MM/DD HH:MM`**。\n
                      - `theme`：提取完整的演出主题名称，需保留书名号（如《XXX》）。\n
                      - `team`：按以下优先级确定：\n
                        a) 若原文有明确的`TEAM`名称（如`TEAM SII`），则直接使用。\n
                        b) 若为**毕业公演、个人演唱会、个人定制公演**，且原文提及成员姓名（如`@SNH48-韩家乐`），则格式为 **`团体名-成员名`**（例如：`SNH48-韩家乐`）。\n
                        c) 否则，根据上下文推断为 **`团体名-描述`**（例如：`SNH48-新生队`）。\n
                    5. **时间处理逻辑**：\n   - 年份：默认使用**{ current_year }年**。\n
                      - **跨年规则**：如果当前月份是**12月**，且解析到的时间是**1月**（如`01/01`、`01/10`），则年份调整为**{ current_year + 1 }年**。当前月份为：{ current_month }月\n
                      - 格式：月份和日期需补零为两位（如`1/7` → `01/07`），时间需保持24小时制，小时和分钟补零为两位（如`19:30`、`09:03`）。\n\n
                    ** 示例输入：
                      1/7（三）19:30《B•RISE 梦之门》新生公演
                      1/8（四）19:30 TEAM X焕新公演《Fire X》

                      ## 示例输出：
                      [
                        {{
                          "time": "2026/01/07 19:30",
                          "theme": "《B•RISE 梦之门》",
                          "team": "SNH48-新生队"
                        }},
                        {{
                          "time": "2026/01/08 19:30",
                          "theme": "《Fire X》",
                          "team": "TEAM X"
                        }}
                      ]
                    **待处理文本：**\n 
                    { texts }\n\n
                    请根据上述规则提取并输出JSON数组。"""
      }
    ]
    logger.info(f"发送给AI的文本长度: {len(json.dumps(content, ensure_ascii=False))}")
    result = request_openai(content)
    logger.debug(f"AI返回结果: {result}")
    if not result or len(json.loads(result)) == 0:
      logger.error("未能从AI获取有效结果")
      return

    update_data(result, "data.js")
    
    result_json = json.loads(result)
    result_json.sort(key=lambda x: datetime.strptime(x['time'], '%Y/%m/%d %H:%M'))
    send_feishu_card_content(result_json)

  except Exception as e:
    logger.error(f"运行过程中发生错误: {e}")


# 调用
with sync_playwright() as playwright:
  run(playwright)