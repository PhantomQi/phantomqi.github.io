20230925-Android不认Java编译的字节码，让我失去了一个周末
===

* [1、问题背景](#1问题背景)
* [2、问题分析](#2问题分析)
   * [2.1、monitor](#21monitor)
   * [2.2、catch和catchall](#22catch和catchall)
   * [2.3、当代码同时涉及synchronized和try-catch的时候](#23当代码同时涉及synchronized和try-catch的时候)
* [3、问题解决](#3问题解决)
   * [3.1、修改效果及结论](#31修改效果及结论)
   * [3.2、回过头来：Java编译输出的字节码真的不够安全吗？](#32回过头来java编译输出的字节码真的不够安全吗)
   * [3.3、遗留问题和其他结论](#33遗留问题和其他结论)

---

# 1、问题背景

我有一个SDK被集成进了SystemUI。SystemUI在周末进行Coverage构建的时候提示如下错误（省略了一些无关的信息，仅保留了关键文字）：

```
dex2oatd method_verifier.cc:5126] void ...c(...) failed to verify: [0x115] expected to be within a catch-all for an instruction when a monitor is held
dex2oatd method_verifier.cc:867] Had a hard failure verifying all classes, and was asked to abort in such situation.
```

我被告知正常构建不会报错，只有Coverage构建会报错。由于我对SystemUI的构建不了解，无法从构建过程入手进行分析，故只能从错误信息本身着手。

# 2、问题分析

从`dex2oat`的源码去分析对我来说显然不现实，所以我聚焦在这段文字本身：

```
expected to be within a catch-all for an instruction when a monitor is held
```

从这段文字可以看到几个关键字：`monitor`、`instruction`、`catch-all`。我决定从略有印象的`monitor`入手。

## 2.1、monitor

在网上一搜，我确认到`monitor`是`synchronized`的字节码（准确的说是smali，但区分他们在本文没有太大意义）。

假设有如下代码：

```kotlin
synchronized(lock) {
    data = 2
}
```

那么编译生成的字节码如下所示：

```assembly
monitor-enter v0
const/4 v1, 0x2
:try_start_4
iput v1, p0, Lphantom/monitor/MainActivity;->data:I
:try_end_8
.catchall {:try_start_4 .. :try_end_8} :catchall_a
monitor-exit v0
return-void
:catchall_a
move-exception v1
monitor-exit v0
throw v1
```

这段字节码包含几个要点：

1. `synchronized`关键字会生成成对的`monitor-enter`和`monitor-exit`指令。
2. 编译器会自动插入一段`try-catch`。插入`try-catch`的目的据说[^1]是为了保障monitor在发生异常的时候不会被泄露。

综合上面两点，`synchronized`关键字的字节码大概会遵循如下模式：

```
monitor-enter
try_start
try_end
catchall
monitor-exit
```

在上面的字节码中出现了`catchall`，正好是SystemUI报错信息中提到的关键字。

## 2.2、catch和catchall

为了了解`catchall`的特别之处，对比下面代码的字节码。

```kotlin
// code 1
try {
    data = 3
} catch (e: Exception) {
    //
}

// code 2
try {
    data = 4
} catch (e: Throwable) {
    //
}
```

上述两端代码生成的字节码如下所示：

```assembly
# code 1
const/4 v0, 0x3
:try_start_1
iput v0, p0, Lphantom/monitor/JavaClass;->data:I
:try_end_3
.catch Ljava/lang/Exception; {:try_start_1 .. :try_end_3} :catch_3

# code 2
const/4 v0, 0x4
:try_start_1
iput v0, p0, Lphantom/monitor/JavaClass;->data:I
:try_end_3
.catchall {:try_start_1 .. :try_end_3} :catchall_3
```

通过上面实验可以看出：

1. `catchall`对应于`catch(Throwable)`，即捕获所有异常。
2. `catch`对应于具体类型的异常捕获。

综上，可以推测SystemUI报错的问题同时涉及`synchronized`语句和`try-catch`语句。

## 2.3、当代码同时涉及synchronized和try-catch的时候

结合报错信息，定位到SDK中的方法，在其中发现了这样一段代码：

```kotlin
try {
    // ... some other code
    synchronized (mLock) {
        // ... some code
    }
} catch (e: Exception) {
    // ... some other code
}
```

这段代码对应的字节码如下：

```assembly
:try_start_135
# ... some other code
monitor-enter v4
:try_end_14d
.catch Ljava/lang/Exception; {:try_start_135 .. :try_end_14d} :catch_16d
:try_start_14f
# some code
:try_end_153
.catchall {:try_start_14f .. :try_end_153} :catchall_166
:try_start_153
# some code
monitor-exit v4
:try_end_158
.catch Ljava/lang/Exception; {:try_start_153 .. :try_end_158} :catch_16d
# ... some other code
```

该字节码有如下要点：

1. 编译器自动插入的`catchall`仍然存在。
2. 编译器额外插入了两段`try-catch`（Line5和Line14），且没有使用`catchall`。

原设想`synchronized`外层的`try-catch`会生成一条`catch`指令，并把整个monitor包裹住。但真实的效果外层`try-catch`被`synchronized`劈成了两段，一段在Line1~5，另一段在Line10~14，且前一段与后一段共享相同的异常类型和异常处理。猜测是`try-catch`不能嵌套，但并未去证实。

基于上述推论，将源码改为：

```kotlin
try {
    // ... some other code
    synchronized (mLock) {
        // ... some code
    }
} catch (e: Throwable) { // <- 把Exception改为Throwable
    // ... some other code
}
```

得到如下字节码：

```assembly
:try_start_1
# ... some other code
monitor-enter v0
:try_end_6
.catchall {:try_start_1 .. :try_end_6} :catchall_11
:try_start_8
# some code
:try_end_c
.catchall {:try_start_8 .. :try_end_c} :catchall_e
:try_start_c
monitor-exit v0
:try_end_11
.catchall {:try_start_c .. :try_end_11} :catchall_11
# ... some other code
```

可见Line5和Line13都变成了`catchall`，而其他字节码并无本质变化。

综上，可以确认当`try-catch`中包含`synchronized`的时候，`try-catch`指令会被`synchronized`劈开，且有一条`catch`/`catchall`会插入在`monitor-enter`之后。

# 3、问题解决

## 3.1、修改效果及结论

经过上面的分析，SystemUI之所以报错是因为Android认为Java编译器在`monitor-enter`和`monitor-exit`之间只能有`catchall`指令，而`catch`指令是不够安全的。

基于上述推论，将SDK中的`catch`异常类型从`Exception`修改为`Throwable`，重新集成到SystemUI做构建，本文开头的报错没有再出现。

**由此得出一条潜规则：当内部直接包含`synchronized`语句的时候，`catch`的类型必须是`Throwable`。**

## 3.2、回过头来：Java编译输出的字节码真的不够安全吗？

源代码：

```kotlin
try {
    // ... some code #1
    synchronized(lock) {
        // ... some code #2
    }
} catch (e: Exception) {
    // ... some code #3
}
```

字节码：

```assembly
:try_start_1
# ... some code #1
monitor-enter v0
:try_end_6
.catch Ljava/lang/Exception; {:try_start_1 .. :try_end_6} :catch_11
:try_start_8
# ... some code #2
:try_end_c
.catchall {:try_start_8 .. :try_end_c} :catchall_e
:try_start_c
monitor-exit v0
goto :goto_11
:catchall_e
move-exception v1
monitor-exit v0
throw v1
:try_end_11
.catch Ljava/lang/Exception; {:try_start_c .. :try_end_11} :catch_11
:catch_11
# ... some code #3
:goto_11
return-void
```

1. 如果不发生任何异常，字节码会从Line1顺序执行到Line11，没有任何跳转，`monitor-enter`和`monitor-exit`是配对的。
2. 如果code #2发生异常，那么会命中Line9的`catchall`，跳过Line11的`monitor-exit`，跳转到Line13的异常处理，执行Line15的`monitor-exit`。`monitor-enter`和`monitor-exit`仍然是配对的。
3. 如果code #1发生异常，有两种情况：
   1. 发生的异常是`Exception`类型：命中Line5，那么Line3的`monitor-enter`不会执行，而是跳转到Line19，不会执行`monitor-exit`。
   2. 发证的异常不是`Exception`类型：不会命中Line5，异常应该会中断代码执行，理论上Line3及之后的所有指令都不会执行，包括Line3的`monitor-enter`在内。

基于上述分析，可以相信：

1. 如果执行进了`synchronized`，`monitor-enter`和`monitor-exit`总是配对的，monitor是安全的。
2. 如果没有执行进`synchronized`，根本就不会进入monitor，monitor也是安全的。

综上可以得出结论：Java编译器生成的字节码是没有问题的。问题的本质可能是：

1. Android机械的认为monitor内部不能有`catch`指令，只能有`catchall`指令。
2. Java编译劈开`try-catch`时大可把`catch`指令放在`monitor-enter`之前，但却放在了`monitor-enter`之后。不管Java编译器的意图为何，但这个结果跟Android的校验规则不合。

## 3.3、遗留问题和其他结论

还有一些问题没能深入研究：

1. 为什么Coverage构建会报错，而正常构建不报错？
2. 为什么把APK直接安装到手机上运行的时候`dex2oat`不会报错，只有在构建的时候报错？
3. Java编译器生成的字节码不能说是错误的，但为啥Android又不认可。既然Android不认可，为啥不在构建的更早环节报错呢？

在解决问题的过程中还得出了如下结论：

1. `try-catch`语句和`runCatching`语句在异常类型为`Throwable`的时候，生成的字节码没有本质区别。
2. Java和Kotlin的`try-catch`语句生成的字节码没有本质区别。

上述结论很容易验证，这里不再赘述。

---

[^1]: [Android smali逆向还原之synchronized原理剖析](https://www.jianshu.com/p/eec7d68df2fe)