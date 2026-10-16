# 人情礼金记账系统 Android APK 打包指南 (Android Build)

> 本文档介绍了如何通过 GitHub Actions CI/CD 流水线自动化将项目打包为独立的 Android 原生 APK 安装包。  
> 快速启动请参考主页 [README.md](../README.md)。

---

## 一、打包方案概览

本项目原生支持通过 Python for Android (`buildozer`) 工具链构建为离线随身携带的 APK 应用，并在 GitHub 托管独立的专有仓库 [gift_bookkeeping_apk](https://github.com/18227370901/gift_bookkeeping_apk.git)。

项目已集成全自动 GitHub Actions 流水线，无需本地繁琐配置 Android SDK / NDK 开发环境，推送代码即可自动产出可安装的 `.apk` 文件。

---

## 二、通过 GitHub Actions 自动化打包流程

1. **触发构建**：
   - 向 `main` 分支推送带有版本标签的代码（例如 `v10.11.x`），或在 GitHub 仓库页面的 **Actions** 标签下点击 **Run workflow** 手动触发打包。
2. **构建环境**：
   - 运行于 `ubuntu-latest` 容器；
   - 自动准备 Python 3.11 环境、安装 Cython 及 Buildozer 依赖库；
   - 自动拉取 Android SDK (API 33) 与 NDK (r25b)。
3. **获取产物**：
   - 构建成功后，进入对应的 Action 运行记录页面；
   - 在底部的 **Artifacts** 区域即可直接下载名为 `gift-bookkeeping-debug.apk` 的安装包文件。

---

## 三、本地安装与离线使用

1. 将下载的 `.apk` 文件传输至 Android 手机或平板设备；
2. 在设备上允许“安装来自未知来源的应用”；
3. 完成安装后即可在离线断网环境下脱机使用人情礼金记账的核心功能。
