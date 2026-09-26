// name: 臭宝乐园
// cron: 40 16,4 * * *
const axios = require("axios");
const fs = require("fs");
const path = require("path");

// Token 缓存
const TOKEN_CACHE_DIR = path.join(__dirname, "token_caches");
const TOKEN_CACHE_FILE = path.join(TOKEN_CACHE_DIR, "cbly_token_cache.json");

function readTokenCache() {
    try {
        if (!fs.existsSync(TOKEN_CACHE_FILE)) return {};
        return JSON.parse(fs.readFileSync(TOKEN_CACHE_FILE, "utf-8")) || {};
    } catch { return {}; }
}

function writeTokenCache(cache) {
    try {
        fs.mkdirSync(TOKEN_CACHE_DIR, { recursive: true });
        fs.writeFileSync(TOKEN_CACHE_FILE, JSON.stringify(cache, null, 2), "utf-8");
    } catch (e) { console.log("⚠️ 缓存写入失败:", e.message); }
}

const REQUEST_TIMEOUT_MS = 20000;
// ====================== YYB Go 账号（环境变量 YYB_SERVER = 地址@微信账号标识，多行） ======================
const SERVERS = (process.env.YYB_SERVER || "")
    .split(/\r?\n/)
    .map(s => s.trim())
    .filter(Boolean);
if (!SERVERS.length) {
    console.error("未配置环境变量 YYB_SERVER，请设置后重试（格式：地址@微信账号标识，多行换行）");
    process.exit(1);
}
function parseYybGoEntry(rawValue) {
    const value = String(rawValue || "").trim();
    if (!value) return { server: "", ref: "" };
    const atIndex = value.indexOf("@");
    if (atIndex === -1) {
        console.log("YYB_SERVER 格式应为 地址@微信账号标识，当前值: " + value);
        return { server: "", ref: "" };
    }
    let server = value.slice(0, atIndex).trim();
    const ref = value.slice(atIndex + 1).trim();
    if (server.startsWith("http://")) server = server.slice(7);
    else if (server.startsWith("https://")) server = server.slice(8);
    server = server.replace(/\/+$/, "");
    if (!server || !ref) return { server: "", ref: "" };
    return { server, ref };
}
async function getCode(server) {
    const { server: parsedServer, ref } = parseYybGoEntry(server);
    if (!parsedServer || !ref) return null;
    const url = "http://" + parsedServer + "/wxapp/getCode";
    try {
        const { data } = await axios.post(url, { ref, app_id: 'wx2206cca563f6f937' }, { timeout: 20000, proxy: false });
        const code = data && data.data && data.data.result && data.data.result.code;
        if (!data || data.code !== 0 || !code) {
            console.log(parsedServer + " 获取code失败: " + JSON.stringify(data));
            return null;
        }
        console.log(parsedServer + " 获取code成功");
        return code;
    } catch (e) {
        console.log(parsedServer + " 获取code异常: " + e.message);
        return null;
    }
}
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
let userIdx = 1;

const strSplitor = "#";

const defaultUserAgent = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.31(0x18001e31) NetType/WIFI Language/zh_CN miniProgram"

class Task {
    constructor(env) {
        this.server = env;
        const _yyb = parseYybGoEntry(this.server);
        this.ref = _yyb.ref;
        this.openid = _yyb.ref;
        this.index = userIdx++
        this.user = env.split(strSplitor);

        this.wcsid = this.openid
    }

    async run() {
        try {
            // 随机延迟5-25s 模拟人工操作
            await sleep(Math.floor(Math.random() * 20 + 5) * 1000);

            // 尝试缓存（不过期，鉴权失败自动重登）
            const cache = readTokenCache();
            const cached = cache[this.server] || {};
            let usedCache = false;
            if (cached.token) {
                this.token = cached.token;
                usedCache = true;
                console.log(`💾 账号[${this.index}] 使用缓存token`);
            }

            for (let attempt = 0; attempt < 2; attempt++) {
                if (attempt === 1 || !this.token) {
                    if (attempt === 1) {
                        console.log(`🔄 账号[${this.index}] token失效，重新登录...`);
                        const c = readTokenCache();
                        delete c[this.server];
                        writeTokenCache(c);
                    }
                    this.token = null;
                    const code = await getCode(this.server)
                    if (code) {
                        await this.getUserToken(code)
                    }
                    if (!this.token) {
                        console.log(`账号[${this.index}] 获取用户Token失败❌`)
                        return
                    }
                    const c = readTokenCache();
                    c[this.server] = { token: this.token };
                    writeTokenCache(c);
                }
                this.token = 'Bearer' + this.token

                const infoOk = await this.getUserInfo()
                await this.track()
                await this.checkSign()

                // 缓存token业务鉴权失败 → 清缓存重登重试一次
                if (usedCache && attempt === 0 && !infoOk) {
                    console.log(`⚠️ 账号[${this.index}] 鉴权失败，判定token失效`)
                    continue;
                }
                break;
            }
        } catch (error) {
            const reason = error?.response?.data?.msg || error?.code || error?.message || String(error);
            console.log(`账号[${this.index}] 请求失败: ${reason}❌`)
        }
    }
    async getUserToken(code) {
        let options = {
            method: 'POST',
            url: `https://cb-bags-slb.weinian.com.cn/bff/v1/auth/wechatLogin`,
            headers: {
                "accept": "*/*",
                "accept-language": "zh-CN,zh;q=0.9",
                "content-type": "application/json",
                "authorization": "Bearer" + this.token
            }
            ,
            data: {
                loginCode: code
            },
            timeout: REQUEST_TIMEOUT_MS
        }
        let {
            data: result
        } = await axios.request(options);
        if (result?.status == '200') {
            this.token = result.data
            console.log(`🌸账号[${this.index}] 获取用户Token成功`)
        } else {
            console.log(`🌸账号[${this.index}] 获取用户Token-失败:${result.msg}❌`)
        }
    }
    async getUserInfo() {
        let options = {
            method: 'POST',
            url: `https://cb-bags-slb.weinian.com.cn/wnuser/v1/memberUser/getMemberUser`,
            headers: {
                "accept": "*/*",
                "accept-language": "zh-CN,zh;q=0.9",
                "authorization": "" + this.token + "",
                "content-type": "application/json",
                "priority": "u=1, i",
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "cross-site",
                "user-agent": 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) UnifiedPCWindowsWechat(0xf254173b) XWEB/19027'
            },
            timeout: REQUEST_TIMEOUT_MS
        }
        let {
            data: result
        } = await axios.request(options);
        if (result?.status == '200') {
            //打印签到结果
            console.log(`🌸账号[${this.index}]` + `[${result.data.nickName}] 积分[${result.data.points}]🎉`);
            return true;
        } else {
            console.log(`🌸账号[${this.index}] 获取用户信息-失败:${result.msg}❌`)
            return false;
        }
    }
    async track() {
        let options = {
            method: 'POST',
            url: `https://cb-bags-slb.weinian.com.cn/member/v1/memberBuryPoint/add`,
            headers: {
                "accept": "*/*",
                "accept-language": "zh-CN,zh;q=0.9",
                "authorization": "" + this.token + "",
                "content-type": "application/json",
                "priority": "u=1, i",
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "cross-site",
                "user-agent": 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) UnifiedPCWindowsWechat(0xf254173b) XWEB/19027'
            },
            data: { "appletVersion": "2.0.31", "phoneSystem": "Windows Unknown x64", "phoneModel": "microsoft", "functionName": "签到", "module": "首页", "linkUrl": "pages/signIn/signIn", "secondPage": "" },
            timeout: REQUEST_TIMEOUT_MS
        }
        await axios.request(options);
    }
    async checkSign() {
        let options = {
            method: 'POST',
            url: `https://cb-bags-slb.weinian.com.cn/wnuser/v1/memberUser/checkSignNum`,
            headers: {
                "accept": "*/*",
                "accept-language": "zh-CN,zh;q=0.9",
                "authorization": "" + this.token + "",
                "content-type": "application/json",
                "priority": "u=1, i",
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "cross-site",
                "user-agent": 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) UnifiedPCWindowsWechat(0xf254173b) XWEB/19027'
            },
            data: {

            },
            timeout: REQUEST_TIMEOUT_MS
        };
        let {
            data: result
        } = await axios.request(options);
        if (result?.status == '200') {
            //打印签到结果
            await this.signIn()
        } else {
            console.log(`🌸账号[${this.index}] 签到状态查询失败:${result?.msg || '未知错误'}❌`)
        }

    }

    async signIn() {
        let options = {
            method: 'POST',
            url: `https://cb-bags-slb.weinian.com.cn/wnuser/v1/memberUser/daySign`,
            headers: {
                "accept": "*/*",
                "accept-language": "zh-CN,zh;q=0.9",
                "authorization": "" + this.token + "",
                "content-type": "application/json",
                "priority": "u=1, i",
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "cross-site"
            },
            data: {

            },
            timeout: REQUEST_TIMEOUT_MS
        };
        let {
            data: result
        } = await axios.request(options);
        if (result?.status == '200') {
            //打印签到结果
            console.log(`🌸账号[${this.index}]` + `签到成功🎉`);
        } else {
            console.log(`🌸账号[${this.index}] 签到-失败:${result.msg}❌`)
        }

    }

}

!(async () => {
    if (true) {
        for (let user of SERVERS) {
            await new Task(user).run();
        }
    } else {
        
        console.log(`${"YYB_SERVER"}未配置微信SERVER配置 搭建可看仓库目录下的readme.md❌`)
        return
    }

})()
    .catch((e) => console.log(e))
    

