# 开发与复现

## 结构

- `translations/*.json`：索引、资源键与中文译文；索引使重复键保持原有先后顺序。
- `patcher.py`：标准库安装器、XOR ZIP 资源重建、严格版本校验、PE 修改及还原。
- `installer.py` / `main.py`：图形安装器与入口。
- `native/render.c`：仅用于 type-2 TrueType 文本的 x86 兼容逻辑。
- `native/payload.bin` / `payload.json`：自有代码的编译结果及重定位位置。
- `assets/Chinese.ttf`：OFL 授权的静态中文字体子集。

游戏资源 `Data.pak` 是逐字节 XOR `0xF8` 的 ZIP。补丁在用户机器上读取已验证的原版，保留原条目顺序、元数据与非文本资源内容，只替换相关文本 / 字体引用并加入开放字体。CSV 的其他列、重复键与换行保留；`%d`、`%s`、`%%`、`$(...)` 等占位符需保持顺序一致。

游戏已有 TrueType / FTGL 支持，但默认分支没有完整实现文本排版。本项目为该分支新增只读可执行 PE 节，调用游戏原有字体渲染功能与 OpenGL 导入。原函数其余分支保留；默认 TrueType 字号改为 60。新的绝对地址操作数加入 PE 基址重定位表，被替换代码内的旧重定位被移除。它不修改 Steam API、授权或存档逻辑。

## 测试

```powershell
python -m pip install -r requirements-dev.txt
pnpm lint
pnpm test
```

也可直接运行 `python -m ruff check .` 和 `python -m unittest discover -s tests -v`。

测试使用合成 ZIP / PE，不需要游戏。要额外核验真实资源及 DLL，请在已经保留受支持原版备份的本地设置：

```powershell
$env:FR2_GAME = "F:\SteamLibrary\steamapps\common\Fieldrunners 2"
pnpm test
```

该集成测试仅读取备份，不启动或修改游戏。不要把原版文件或测试者存档加入仓库。

## 重建字体

下载上游 `NotoSansSC[wght].ttf`，核验 `assets/FONT-NOTICE.md` 中的源文件 SHA-256。使用 fontTools 静态化到 weight 550，按该说明中的字符集进行子集化，保留名称记录，然后将名称 ID 1、4、6 分别设置为 `FR2 Chinese UI`、`FR2 Chinese UI`、`FR2ChineseUI`。保留字体原版权记录及 OFL。

`native/metrics.h` 由子集字体的 Unicode cmap 与 hmtx 生成，宽度按 `round(advance * 1000 / unitsPerEm)` 归一化为 1000 单位，按码点排序。可运行：

```powershell
python -m tools.rebuild_resources --font-source "C:\Downloads\NotoSansSC[wght].ttf"
python -m tools.rebuild_resources --game-dir "F:\SteamLibrary\steamapps\common\Fieldrunners 2"
```

后一个命令只读取原版，重建 `native/fallback.h` 中的缓存关卡转译表：仅存储源文本的长度、双重 32 位哈希和中文，不包含英文原文或存档。字体、译文字符集或缓存映射改变后须同步重建 native payload。

## 重建 x86 代码

需要支持 `-m32` 对象输出及 `i386pe` 链接的 GNU gcc / ld，以及 pefile、capstone。已使用 MinGW GCC 15.2.0 验证。无需游戏原版文件。

```powershell
$env:MINGW_BIN = "D:\mingw64\bin"
python native/build.py
pnpm lint
pnpm test
```

编译器选项、固定链接位置及重定位扫描都在 `native/build.py`。发行 payload 在 `0x103B1000` 开始；此布局只适配 README 指定哈希的 DLL。

## 构建独立安装器

```powershell
python -m PyInstaller --noconfirm --clean --onefile --windowed --name Fieldrunners2-ZH-v0.1.0 --add-data "assets;assets" --add-data "translations;translations" --add-data "native/payload.bin;native" --add-data "native/payload.json;native" main.py
```

产物在 `dist/`，以 Windows x64 Python 构建。发布前应在真实 Steam 游戏中验证安装、还原、再次安装、主菜单、设置、长文本及战斗界面，并明确记录未验证的范围。
