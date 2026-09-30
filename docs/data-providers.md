# 数据源扩展接口

`DataProviderInterface` 按能力组合三个接口，默认 `public` 配置继续使用现有 Yahoo、DuckDuckGo / HN 和 FRED。主管、采集节点和研究工具都通过同一组适配器访问数据，不再在业务节点实例化具体公共数据源。

| 接口                                  | 返回契约                          | 实现责任                                                                    |
| ------------------------------------- | --------------------------------- | --------------------------------------------------------------------------- |
| `MarketDataProvider.history / lookup` | `MarketDataset` / 资产检索记录    | OHLCV、复权定义、时区/交易日历、来源 URL、采集时间与内容哈希                |
| `NewsDataProvider.search / read`      | 搜索线索 / `(SourceRecord, 原文)` | 搜索摘要不作为已读证据；保留发布日期、原文定位、来源及版权范围              |
| `MacroDataProvider.series`            | `(日期数值序列, SourceRecord)`    | 当前研究使用 CPIAUCNS / DGS3MO 的语义；厂商代码在适配器内映射，披露修订口径 |

适配器必须把单位、币种、复权、交易时点映射为既有领域契约。接口一致不等于不同厂商的金融口径天然一致；不满足请求时应报错或缺失，不能静默返回其他资产。公共适配器原有网络、SSRF、重定向及缓存边界保留。

## 插件安装与选择

扩展包注册 Python entry point：

```toml
[project.entry-points."evidence_research.providers"]
licensed = "my_data_plugin:create_providers"
```

插件工厂可以只替换行情能力，复用其他公共源：

```python
import os
from dataclasses import replace
from research_app.data_providers import public_providers
from .market import LicensedMarketProvider  # 扩展包实现对应厂商 SDK 与口径映射


def create_providers(settings):
    return replace(
        public_providers(),
        market=LicensedMarketProvider(api_key=os.environ["LICENSED_DATA_KEY"]),
    )
```

安装扩展包后，在服务端 `.env` 设置 `RESEARCH_PROVIDER_PROFILE=licensed` 并重启。密钥只从服务端读取，不写入工厂返回对象的来源记录、URL、日志或 Bundle。扩展包属于运维人员安装的可信代码；Agent 无权安装包、指定模块路径或选择未注册的数据源。

资讯 `web` 是默认路由，可替换为专有新闻源；也可添加命名路由，研究工具仅接受已注册名称。`read_public_source` 的 `provider` 与搜索路由一致，默认 `web`。插件应提供公开可回链 URL 和可保存的授权原文，并遵守商业数据使用/再分发条件；不要将认证参数拼入来源链接。

测试或内嵌服务可通过 `Pipeline(..., providers=DataProviders(...))` 注入，无需 entry point。`tests/test_data_providers.py` 验证注册选择、未知配置拒绝、采集替换与公共资讯边界。

本次交付扩展接口与可运行的公共实现，未冒充已完成 Tushare、Wind 或 Bloomberg 的接入。这些服务的账户、许可、具体 SDK 与市场覆盖应由实际接入项目确定，无凭据时不引入空壳适配器。
