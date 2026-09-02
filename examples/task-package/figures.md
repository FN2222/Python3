# 本章可用图片清单(只能引用下表中的 figure_id)

共 2 张。`预览` 列是相对本文件的路径,可直接打开查看。

| figure_id | 页码 | 类型 | 尺寸 | 推测图注 | 上方标题 | 预览 |
| --- | --- | --- | --- | --- | --- | --- |
| `fig-p001-1` | 1 | raster | 900x380 | Figure: Introduction to OSPF Neighbor Adjacency diagram | Two routers become neighbors only when t | [fig-p001-1.png](../../extract/ospf-neighbor-adjacency-69619352/figures/fig-p001-1.png) |
| `fig-p003-1` | 3 | raster | 900x380 | Figure: Designated Router Election diagram | Designated Router Election | [fig-p003-1.png](../../extract/ospf-neighbor-adjacency-69619352/figures/fig-p003-1.png) |

> ⚠️ **重要**:拓扑图里的设备名、接口名、网段这些文字**存在于图片像素中,不在 PDF 文本层**。
> 所以引用某张图时,必须在 `figures[].labels_seen` 里把你从图上读到的标签逐字登记,
> 否则笔记里写 `R1`、`10.0.0.0/24` 会被门禁判为臆想。

## 每张图的原文周边上下文(判断这张图在讲什么)

### `fig-p001-1` — 第 1 页

- 推测图注: Figure: Introduction to OSPF Neighbor Adjacency diagram
- 上方标题: Two routers become neighbors only when the hello interval, the dead interval,

```text
packets to discover neighbors on a link. The hello packet is sent to multicast address 224.0.0.5 every 10 seconds on a broadcast network segment. Two routers become neighbors only when the hello interval, the dead interval, the area ID and the subnet mask all match. The dead interval is 40 seconds by default, which is four times the hello interval. Figure: Introduction to OSPF Neighbor Adjacency diagram
```

### `fig-p003-1` — 第 3 页

- 推测图注: Figure: Designated Router Election diagram
- 上方标题: Designated Router Election

```text
esignated router and a backup designated router. The router with the highest OSPF priority becomes the designated router. When the priority is equal, the router with the highest router ID wins the election. A priority of 0 means the router will never become the designated router. All other routers form a full adjacency only with the DR and the BDR. Figure: Designated Router Election diagram
```
