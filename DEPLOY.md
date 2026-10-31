# Fin Analyzer 部署指南

本指南教你如何将 Fin Analyzer 的 Web 版本部署到公网，让任何人都能通过浏览器使用。

---

## 方式一：Hugging Face Spaces（推荐）

Hugging Face Spaces 支持从任意公开 Git 仓库部署，包括 GitHub。

### 步骤

1. 访问 [huggingface.co/spaces](https://huggingface.co/spaces)，注册/登录
2. 点击 **+ New Space**
3. 填写配置：
   - **Space Name**: `fin-analyzer`（或你喜欢的名字）
   - **License**: `mit`
   - **SDK**: `Streamlit`
   - **SDK Version**: 选最新稳定版
4. 点击 **Create Space**
5. 创建后，在 Space 页面选择 **Settings** → 找到 **Repository** 部分
6. 填入你的 GitHub 仓库地址：`https://github.com/Yumm-del/fin-analyzer.git`
7. 在 Settings → **Repository secrets** 中添加：
   ```
   DEEPSEEK_API_KEY = sk-你的密钥
   ```
8. Space 会自动拉取代码、安装依赖、启动服务
9. 几分钟后，你的公网地址就是 `https://huggingface.co/spaces/<你的用户名>/fin-analyzer`

### 优势
- ✅ 免费
- ✅ 不需要单独部署服务器，绑定仓库即可
- ✅ 自动 HTTPS
- ✅ 不使用时自动休眠（节省资源）

---

## 方式二：Streamlit Community Cloud（免费，需要 GitHub）

Streamlit 官方云服务，但要求代码托管在 GitHub。

### 步骤

1. 仓库已在 GitHub（`Yumm-del/fin-analyzer`），无需额外镜像
2. 访问 [share.streamlit.io](https://share.streamlit.io)，用 GitHub 登录
3. 点击 **New app**
4. 选择仓库、分支（master）、主文件路径（app.py）
5. 在 **Advanced settings** 中，添加 Secret：
   ```
   DEEPSEEK_API_KEY = "sk-你的密钥"
   ```
6. 点击 **Deploy**

### 优势
- ✅ 免费
- ✅ Streamlit 官方支持，兼容性最好
- ✅ 提供应用分析（访问量等）

---

## 方式三：自建服务器部署

适合有云服务器的场景（阿里云、腾讯云轻量服务器等）。

### 步骤

```bash
# 1. 在服务器上克隆代码
git clone https://github.com/Yumm-del/fin-analyzer.git
cd fin-analyzer

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置 API Key
echo 'DEEPSEEK_API_KEY=sk-你的密钥' > .env

# 4. 后台启动（使用 nohup 或 tmux）
nohup streamlit run app.py --server.port 8501 --server.address 0.0.0.0 &

# 5. 配置 Nginx 反向代理 + HTTPS（可选但推荐）
```

### 优势
- ✅ 完全控制
- ✅ 国内访问更快（如果服务器在国内）

---

## 方式四：本地局域网使用

不需要公网部署，同一 WiFi 下的设备都能访问。

```bash
# 启动时绑定到所有网络接口
streamlit run app.py --server.address 0.0.0.0

# 局域网内的其他设备通过 http://<你的电脑IP>:8501 访问
```

查看本机 IP：
- Windows: `ipconfig` 找到 IPv4 地址
- Mac/Linux: `ifconfig` 或 `ip addr`

---

## 配置 API Key 的方式汇总

| 方式 | 适用场景 | 配置位置 |
|------|---------|---------|
| 侧边栏输入 | 临时使用 | Web UI 中直接输入 |
| `.env` 文件 | 本地开发 | 项目根目录 `.env` |
| 环境变量 | 服务器部署 | `export DEEPSEEK_API_KEY=...` |
| Streamlit Secrets | Streamlit Cloud | 部署设置页面的 Secrets 区 |
| HF Secrets | Hugging Face Spaces | Space Settings → Repository secrets |

---

## 常见问题

### Q: 部署后搜索功能不工作？
A: DuckDuckGo 在某些云服务器上可能被限制。代码已内置 fallback 机制——搜索失败时会使用 LLM 训练数据。如果完全不可用，可考虑后续接入搜索 API（如 SerpAPI）。

### Q: DeepSeek API 调用失败？
A: 检查：
1. API Key 是否正确（Secret 中的空格会被保留）
2. DeepSeek 余额是否充足
3. 部署服务器的出网是否正常

### Q: 免费额度够用吗？
A: DeepSeek 新用户有免费额度，V3 模型价格极低（约 0.001 元/千 tokens）。一次分析大约消耗 2000-4000 tokens，免费额度足够大量使用。
