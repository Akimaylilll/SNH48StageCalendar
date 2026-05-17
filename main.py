from playwright.sync_api import Playwright, sync_playwright
from openai import OpenAI
from dotenv import load_dotenv
import time
import json
import os
import logging
import requests
from datetime import datetime
from functools import cmp_to_key
from brain import Brain

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
      temperature=0.3  # 降低随机性，提高一致性
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


def update_data(result, file_path, brain=None):
    data_json = read_json_from_file(file_path)
    if not data_json:
        logger.warning("data.js文件为空或不存在")
        return None
    data_json = json.loads(data_json)
    result_json = json.loads(result)

    # 使用brain进行智能过滤和去重
    if brain:
        # 过滤非公演信息
        result_json = brain.filter_events(result_json)
        logger.info(f"过滤后剩余 {len(result_json)} 条记录")

        # 规范化主题和团队
        for item in result_json:
            item["theme"] = brain.normalize_theme(item.get("theme", ""))
            item["team"] = brain.normalize_team(item.get("team", ""))

    # 获取当前日期
    from datetime import datetime

    current_date = datetime.now().strftime("%Y/%m/%d")

    # 从data.js中筛选当前日期之后的数据
    future_data = []
    past_data = []
    for item in data_json:
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

    # 将新提取的数据与当前日期之后的数据进行去重
    if brain:
        # 合并新数据和未来数据
        combined = future_data + result_json
        # 去重
        deduplicated = brain.deduplicate_events(combined)
        logger.info(f"去重后剩余 {len(deduplicated)} 条记录")

        # 计算新增的记录数
        new_count = len(deduplicated) - len(future_data)
        if new_count < 0:
            new_count = 0
    else:
        # 如果没有brain，直接合并
        deduplicated = future_data + result_json
        new_count = len(result_json)

    # 合并所有数据：过去的数据 + 去重后的未来数据
    all_data = past_data + deduplicated
    all_data.sort(key=cmp_to_key(sort_custom_key))

    write_to_file(json.dumps(all_data, ensure_ascii=False), file_path)
    logger.info(f"\n数据已成功更新到data.js文件，新增{new_count}条记录")
    logger.info(f"总共有{len(all_data)}条记录")


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
  if not mymblog_statuses_flag:
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
  if not mymblog_statuses_flag:
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
  brain = Brain()
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
    # 使用brain进行提取+学习+数据合并去重（一次完成）
    result_json = brain.learn_from_texts(texts, request_openai, data_file="data.js")
    if not result_json:
          logger.error("未能从AI获取有效结果")
          return

    logger.debug(f"提取+学习+合并结果: {len(result_json)} 条")
    
    result_json.sort(key=lambda x: datetime.strptime(x["time"], "%Y/%m/%d %H:%M"))
    send_feishu_card_content(result_json)

  except Exception as e:
    logger.error(f"运行过程中发生错误: {e}")


# 调用
with sync_playwright() as playwright:
  run(playwright)