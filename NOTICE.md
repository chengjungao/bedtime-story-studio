# 许可与致谢

## 本项目

代码 **MIT**。**不含任何模型权重，也不含上游代码。**

装好之后你的目录里会出现 `CosyVoice/` 和 `.venv/`，两个都是运行时产生的，
不在本仓库里。

## 运行时用到的东西

| 东西 | 谁做的 | 许可 |
|---|---|---|
| [CosyVoice](https://github.com/FunAudioLLM/CosyVoice) | 阿里巴巴通义实验室 FunAudioLLM | Apache-2.0 |
| [Fun-CosyVoice3-0.5B-2512](https://huggingface.co/FunAudioLLM/Fun-CosyVoice3-0.5B-2512) | 同上 | apache-2.0 |
| [PyTorch](https://pytorch.org/) | Meta / Linux 基金会 | BSD-3-Clause |
| [ffmpeg](https://ffmpeg.org/) | FFmpeg 项目 | LGPL-2.1+（部分构建为 GPL） |

本项目把 CosyVoice 当作**独立程序**调用（`python worker_tts.py`），
不改它一行代码，也不把它打包进来。

## 一条不是法律条文但同样要紧的话

**只做自己的声音。**

这套东西能把一段十几秒的录音变成一整篇朗读，所以更要想清楚边界：
拿别人的声音做内容，属于侵权，录音是不是你自己录的、是不是你自己买的，都不影响这个判断。
法院的判准很朴素：普通听众能不能认出这是谁。

给孩子做的睡前故事，本来也只需要一个声音。你自己的那个。

## 关于「0 元」

本项目是免费的开源项目，跑起来也不调用任何付费接口。
但「免费」不等于「没有成本」：模型权重 5.05 GB、PyTorch 2.5 GB、
跑一整篇要占着显卡几分钟。**代价是电、时间和硬盘，不是钱。**
