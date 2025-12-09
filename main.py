from playwright.sync_api import Playwright, sync_playwright
from openai import OpenAI
from dotenv import load_dotenv
from dateutil import parser
import time
import json
import os
import logging

load_dotenv() 

log_level = os.getenv("LOG_LEVEL", "INFO")
openai_api_key = os.getenv("OPENAI_API_KEY")
openai_api_base_url = os.getenv("OPENAI_API_BASE_URL")
openai_model = os.getenv("OPENAI_MODEL")

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
    page.wait_for_timeout(1500)
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
            setTimeout(checkHeight, 2000); // 每2s检查一次  大于page.wait_for_timeout(1500)否则报错
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
    {'role': 'system', 'content': '你是一个专业的数据提取助手，专门过滤重复信息，请忽略theme和team的少部分表达差异，在theme中都添加书名号《》后再判断是否重复，但是注意time_zh时间日期不同的相同theme不属于重复。只输出严格的JSON格式，不包含其他文字。'},
    {'role': 'user', 'content': json.dumps(result_json, ensure_ascii=False)}
  ]
  filter_result_data = request_openai(messages)
  filter_result_data_json = json.loads(filter_result_data)
  data_json_rest.extend(filter_result_data_json)
  data_json_all = [
      {key: value for key, value in d.items() if key != 'time_zh'}
      for d in data_json_rest
  ]
  write_to_file(json.dumps(data_json_all, ensure_ascii=False), file_path)
  logger.info(f"\n数据已成功更新到data.js文件，新增{len(data_json) - len(data_json_rest)}条记录")
  logger.info(f"总共有{len(data_json_rest)}条记录")

# 创建浏览器
def run (playwright: Playwright) -> None:
  try:
    # 创建浏览器
    browser = playwright.chromium.launch(headless=True)
    content = browser.new_context()

    timestamp_template = "%a %b %d %H:%M:%S %z %Y" # Tue Dec 02 12:34:34 +0800 2025
    time_range = 60 * 60 * 12
    mblogs = []

    # 定义响应事件处理函数
    def handle_response(response):
      try:
        # 筛选接口，例如包含"/api/data"的URL
        if "/ajax/statuses/mymblog" in response.url:
          logger.debug(f"捕获到响应 URL: {response.url}")
          logger.debug(f"状态码: {response.status}")
          
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
        elif "/ajax/statuses/show" in response.url:
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

    for url in weibo_urls:
      try:
        blog_list = []
        page = content.new_page()
        # 绑定监听器到“response”事件
        page.on("response", handle_response)
        # 页面打开指定网址
        logger.debug(f"正在访问: {url}")
        page.goto(url)
        page.wait_for_load_state('networkidle')
        # 等待内容加载
        wait_for_scroll_to_bottom(page, timeout=1000 * 60 * 10)

        for item in blog_list:
          try:
            created_at = item.get('created_at', '')
            if not created_at:
              continue

            t = time.mktime(time.strptime(created_at, timestamp_template))
            if t < time.time() - time_range: # 7 天
              continue

            mblogid = item.get('mblogid', '')
            user = item.get('user', {})
            user_idstr = user.get('idstr', '') if user else ''
            
            if mblogid and user_idstr:
              mblog_url = f"https://weibo.com/{user_idstr}/{mblogid}"
              logger.debug(f"访问微博详情: {mblog_url}")
              page.goto(mblog_url)
              page.wait_for_load_state('networkidle')
              page.wait_for_timeout(10000)
          except Exception as e:
            logger.error(f"处理博客项时出错: {e}")
          page.wait_for_timeout(5000)
        
        page.close()

      except Exception as e:
        logger.error(f"处理URL {url} 时出错: {e}")
        continue

    content.close()
    browser.close()

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
    prompt = """
      帮我将上面信息中的所有购票信息整理为json格式，只包含time，theme，team三个英文属性。
      只关注公演、演唱会和运动会的演出时间信息，见面会和握手会等其他信息不统计，请忽略。只有毕业公演、个人演唱会和个人定制公演添加毕业人名，有TEAM名称优先考虑。      
      格式如下:
      [
        {
          "time": "2025/12/10 19:30",
          "theme": "《B•RISE 梦之门》",
          "team": "新生队"
        },
        {
          "time": "2025/12/11 19:30",
          "theme": "《赫兹共振》",
          "team": "TEAM HII"
        },
        {
          "time": "2025/12/06 14:00",
          "theme": "SNH48偶像运动会",
          "team": "SNH48 GROUP"
        },
        {
          "time": "2025/12/20 19:00",
          "theme": "《viva la vida》2024年度MVP定制公演",
          "team": "GNZ48-张琼予"
        },
        {
          "time": "2025/12/20 13:30",
          "theme": "《爱的具象化》毕业公演",
          "team": "SNH48-沈小爱"
        }
      ]
    """
    prompt = prompt + f"\n只输出有效的JSON数组，不要包含其他文字，time格式为 2025/12/01 19:30 、2025/2/02 9:03，没有年份使用当前年份，当前为{current_year}年。"
    texts.append(prompt)
    texts_str = '\n------------\n'.join(texts)
    logger.info(f"发送给AI的文本长度: {len(texts_str)}")
    content = [
      {'role': 'system', 'content': '你是一个专业的数据提取助手，专门从文本中提取公演、演唱会和运动会的演出时间信息。只输出严格的JSON格式，不包含其他文字。'},
      {'role': 'user', 'content': texts_str}
    ]
    result = request_openai(content)
    logger.debug(f"AI返回结果: {result}")
    if not result:
      logger.error("未能从AI获取有效结果")

    update_data(result, "data.js")

  except Exception as e:
    logger.error(f"运行过程中发生错误: {e}")


# 调用
with sync_playwright() as playwright:
  run(playwright)