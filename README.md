# 人化课程阅读器

按真实学习方式阅读需要登录的课程平台：**从第一课开始，一次只打开一页**，读完正文和拓扑图、整理成可读文件后，再进入下一课。

不会并发拉取大量章节，也不会一次性批量请求全部页面。遇到验证码、登录墙、403 / 429 等访问限制时**立刻停止并等待人工处理**，不会尝试绕过。

## 适用场景

- 你已经有该课程的合法访问权限（需要登录）。
- 希望把课程一页页整理成本地 Markdown，方便日后复习。
- 站点可能检测自动化或限制访问频率。

## 不会做的事

- 不自动填写登录表单、不破解验证码、不绕过 403/429。
- 不根据目录把全部章节 URL 先收集再并发抓取。
- 不提供隐身浏览器、指纹伪装、代理轮换等对抗检测功能。

## 安装

核心功能只用 Python 3 标准库：

```bash
python3 -m human_reader course --help
```

若课程页依赖 JavaScript，才需要可选浏览器：

```bash
pip install playwright
python3 -m playwright install chromium
```

## 使用步骤

### 1. 先在自己的浏览器里登录

工具不会替你登录。请用平常的浏览器打开课程，完成登录（含验证码、短信、二次验证）。

然后导出会话，任选一种方式：

- Cookie：浏览器扩展导出 Netscape `cookies.txt`，或 JSON 数组
- Playwright：`--login-wait` 登录成功后 `--save-storage auth.json`

没有会话时，很多平台只能看到目录或试读，读不到全部正文。这是权限问题，不是靠“读得更快”能解决的。

### 2. 从第一课开始顺序阅读

```bash
python3 -m human_reader course 'https://example.com/course/lesson/1' \
  --cookies cookies.txt \
  --save-dir output/course \
  --speed 1
```

阅读节奏：

1. 进入当前课程页  
2. 按屏滚动，读完正文  
3. 查看本页配图 / 拓扑图（逐张，不并发）  
4. 整理并保存这一课的 Markdown  
5. 才解析本页上的「下一课 / 下一页」并打开下一页  

`--speed 1` 接近真人阅读速度。预览流程可用 `--speed 10` 或 `--speed 0`（仍按动作顺序执行，只是不等待）。

### 3. 遇到限制就停

若出现验证码、登录验证、没有权限、HTTP 403 / 429 / 401，进程会停止，并保留已经读完的笔记。请在浏览器里处理后再继续：

```bash
python3 -m human_reader course 'https://example.com/course/lesson/1' \
  --cookies cookies.txt \
  --save-dir output/course \
  --resume
```

### JavaScript 课程平台

```bash
python3 -m human_reader course 'https://example.com/course/lesson/1' \
  --browser --login-wait --headed \
  --save-storage auth.json \
  --save-dir output/course
```

仍然只用**一个标签页**往下翻，不会开多个页面同时读。

## 输出

```
output/course/
  README.md          按阅读顺序排列的目录
  FULL.md            由已读笔记拼接的全文（不是另一次批量抓取）
  state.json         进度；停止原因；下一课地址
  01-第一课标题/
    lesson.md
    assets/          本页配图与拓扑图
```

## 其它命令

若你已经有一份 URL 清单，仍然会逐个打开，而不是并行：

```bash
python3 -m human_reader read-list urls.txt --speed 1 --save-dir output/screens
```

## 测试

```bash
python3 -m unittest discover -s tests -v
```
