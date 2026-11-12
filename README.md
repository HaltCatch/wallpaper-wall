# Wallpaper Wall

[中文](README.md) · [English](README.en.md)

把散落的壁纸整理成可浏览、可收藏、可同步的图库。Wallpaper Wall 面向自托管场景，将系统图库、个人上传和桌面/手机壁纸助手连接起来，既能作为展示墙，也能作为日常选图工具。

## 在线体验

[GitHub Pages](https://haltcatch.github.io/wallpaper-wall/) · 使用合成示例图库体验浏览、预览与收藏。

## 功能

- 流畅浏览：虚拟化瀑布流、横竖屏筛选、文件夹目录、搜索与多尺寸预览。
- 收藏与个人图库：收藏管理、上传配额与独立的个人存储空间。
- 灵活认证：内置账号、OIDC 或混合模式，可配置注册、邀请码与管理员身份。
- 两类存储：本地目录与 S3 兼容对象存储，配合限时媒体地址。
- 桌面与移动端：提供壁纸助手源码和协议入口，下载地址可由部署方配置。
- 背景联动：可将选定壁纸同步到 Homepage，并调整背景卡片与外观预设。

## 快速开始

推荐使用 Docker Compose。前端开发使用 Node.js 26 与 `web/package.json` 固定的 pnpm；后端为 Python/FastAPI。

```sh
cp .env.example .env
# Configure image directory, origin and authentication in .env.
docker compose -p wallpaper-wall up -d --build
```

## 配置

| 配置项 | 说明 |
| --- | --- |
| `WALLPAPER_IMAGES_DIR` | 系统图库根目录，以只读方式挂载。 |
| `WALLPAPER_PUBLIC_ORIGIN` | 实际访问来源；本机 HTTP 调试时相应关闭安全 Cookie。 |
| `WALLPAPER_AUTH_MODE` | `local`、`oidc`、`hybrid` 或 `disabled`。 |
| `WALLPAPER_SESSION_SECRET` | 会话密钥；留空时在数据卷生成。 |
| `WALLPAPER_STORAGE_DRIVER` | `local` 或 `s3`；S3 连接信息在同一示例文件中配置。 |
| `WALLPAPER_USER_STORAGE_QUOTA_BYTES` | 个人存储配额。 |
| `WALLPAPER_HOMEPAGE_SYNC_URL / WALLPAPER_HOMEPAGE_SYNC_SECRET` | 可选 Homepage 背景同步及独立签名凭据。 |

## 使用

默认服务端口为 `4000`。首次使用前，在 `.env` 指定图片目录和访问来源；管理员、OIDC 与桌面助手下载地址可按需要启用。媒体文件版权由各自权利人所有。

## 项目结构

- `web/` — 浏览器图库
- `server/` — 认证、图库与媒体 API
- `wallpaper-agent/` — 桌面助手
- `mobile/` — 移动端助手

## 许可

[PolyForm Noncommercial 1.0.0](LICENSE)。原创部分与第三方组件的适用范围见 [LICENSE_SCOPE.md](LICENSE_SCOPE.md)；各第三方版权和许可见相应声明文件。
