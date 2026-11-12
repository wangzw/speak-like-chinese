# 链接、图片和 HTML

[链接文字](https://example.com/a,b "标题, 带逗号") 只留文字。
![图片说明, 带逗号](https://example.com/x.png) 整个去掉。
裸地址 https://example.com/path?a=1&b=2 去掉。
尖括号自动链接 <https://example.com/a,b> 去掉。
<img alt="中文, 属性" src="x.png"> 标签和属性都去掉。
{{< figure src="a.png" caption="图注, 带逗号" >}}
<!-- 单行注释, 里面的半角逗号不报 -->
<!--
多行注释, 不报。
"引号" 也不报。
-->
{{< figure
    caption="跨行的 shortcode, 不报"
>}}
<img
  alt="跨行的标签, 不报"
  src="a.png">

<pre>
预格式块, 不报
</pre>

{{< highlight go >}}
中文, 代码
{{< /highlight >}}

参考式链接[文档][ref]只留文字。

[ref]: https://example.com "参考定义, 不报"

## 应报

<span>标签之间的文字, 要报</span>
链接后的半角逗号 [文档](https://example.com), 要报。
