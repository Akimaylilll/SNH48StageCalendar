# SNH48 Stage Calendar

这是一个自动化项目，用于抓取微博上SNH48 Group发布的公演票务信息，并将其整理成易于查看的日历形式。

## 项目简介

本项目通过爬虫技术定期从微博平台获取SNH48 Group官方发布的公演票务信息，利用OpenAI接口对这些信息进行智能分析和结构化处理，最终生成静态的日历页面并通过GitHub Actions自动部署到GitHub Pages上。

在线访问: https://akimaylilll.github.io/SNH48StageCalendar/

## 技术架构

- **数据采集**: 使用爬虫技术从微博平台抓取SNH48 Group的公演票务信息
- **数据分析**: 集成OpenAI接口对原始文本信息进行解析，提取出演出时间、地点、剧目等关键信息
- **数据存储**: 将结构化的公演数据写入静态文件
- **自动部署**: 基于GitHub Actions实现CI/CD，自动部署到GitHub Pages
- **前端展示**: 提供直观的日历界面展示公演安排

## 工作流程

1. 定期运行爬虫程序抓取微博上的最新公演信息
2. 调用OpenAI API对抓取的文本内容进行智能分析和数据提取
3. 将解析后的结构化数据保存为静态JSON文件
4. 通过GitHub Actions自动构建并部署到GitHub Pages
5. 用户可通过网页浏览最新的公演日程安排

## 特点优势

- 🤖 自动化程度高，无需人工干预
- 📅 信息展示直观，采用日历形式便于查看
- 🔄 实时更新，始终保持最新公演信息
- ☁️ 免费托管，基于GitHub生态构建

## 使用说明

直接访问 [https://akimaylilll.github.io/SNH48StageCalendar/](https://akimaylilll.github.io/SNH48StageCalendar/) 即可查看最新的SNH48 Group公演安排。

## 开发相关

### 环境依赖

- Python爬虫框架Playwright
- OpenAI API密钥
- GitHub Actions工作流配置

## 注意事项

- 本项目仅用于学习交流目的
- 所有数据来源于公开的微博信息
- 如有侵权请联系删除

## 许可证

MIT License