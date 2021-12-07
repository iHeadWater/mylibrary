# 编写第一个C程序

第一个例子一般都是打印hello world，这里也不例外，用C 语言编写程序，可以这样：

```C
# include <stdio.h>

/* main: generate some simple output */

int main(void)
{
    printf("Hello, world.\n");
    return 0;
}
```

本文件夹下已经有了这个程序文件了，编译执行即可：

```Shell
$ gcc main.c
$ ./a.out
Hello, world.
```

gcc是Linux平台的C编译器，编译后在当前目录下生成可执行文件a.out，直接在命令行输入这个可执行文件的路径就可以执行它。如果不想把文件名叫a.out，可以用gcc的-o参数自己指定文件名：

```Shell
$ gcc main.c -o main
$ ./main
Hello, world.
```

虽然这只是一个很小的程序，但如果之前没深入过C，目前就暂时还不具备相关的知识来完全理解这个程序，比如程序的第一行，还有程序主体的int main(void){...return 0;}结构，这些部分暂时不详细解释，现在只需要把它们看成是每个程序按惯例必须要写的部分（Boilerplate）。但要注意main是一个特殊的名字，C程序总是从main里面的第一条语句开始执行的，在这个程序中是指printf这条语句。

编译器对于语法错误是毫不留情的，如果你的程序有一点拼写错误，例如第一行写成了stdoi.h，在编译时会得到错误提示：

```Shell
$ gcc main.c
main.c:1:19: error: stdoi.h: No such file or directory
```

有些时候编译器的提示信息不是error而是warning，例如把上例中的printf("Hello, world.\n");改成printf(1);然后编译运行：

```Shell
$ gcc main.c
main.c: In function ‘main’:
main.c:7: warning: passing argument 1 of ‘printf’ makes pointer from integer without a cast
$ ./a.out 
Segmentation fault
```

这个警告信息是说类型不匹配，但勉强还能配得上。警告信息不是致命错误，编译仍然可以继续，如果整个编译过程只有警告信息而没有错误信息，仍然可以生成可执行文件。但是，警告信息也是不容忽视的。出警告信息说明你的程序写得不够规范，可能有Bug，虽然能编译生成可执行文件，但程序的运行结果往往是不正确的，例如上面的程序运行时出了一个段错误，这属于运行时错误。各种警告信息的严重程度不同，像上面这种警告几乎一定表明程序中有Bug，而另外一些警告只表明程序写得不够规范，一般还是能正确运行的，有些不重要的警告信息gcc默认是不提示的，但这些警告信息也有可能表明程序中有Bug。一个好的习惯是打开gcc的-Wall选项，也就是让gcc提示所有的警告信息，不管是严重的还是不严重的，然后把这些问题从代码中全部消灭。比如把上例中的printf("Hello, world.\n");改成printf(0);然后编译运行：

```Shell
$ gcc main.c
$ ./a.out
```

编译既不报错也不报警告，一切正常，但是运行程序什么也不打印。如果打开-Wall选项编译就会报警告了：

```Shell
$ gcc -Wall main.c
main.c: In function ‘main’:
main.c:7: warning: null argument where non-null required (argument 1)
```

如果printf中的0是你不小心写上去的（例如错误地使用了编辑器的查找替换功能），这个警告就能帮助你发现错误。强烈建议写每一个编译命令时都加上-Wall选项。

另外注意程序中的注释，注释可以跨行，也可以穿插在程序之中，看下面的例子。

```C
#include <stdio.h>

/* 
 * comment1
 * main: generate some simple output
 */

int main(void)
{
	printf(/* comment2 */"Hello, world.\n"); /* comment3 */
	return 0;
}
```

第一个注释跨了四行，头尾两行是注释的界定符（Delimiter）/*和*/，中间两行开头的*号（Asterisk）并没有特殊含义，只是为了看起来整齐，这不是语法规则而是大家都遵守的C代码风格（Coding Style）之一，后续会介绍更多关于代码风格的内容。

使用注释需要注意两点：

注释不能嵌套（Nest）使用，就是说一个注释的文字中不能再出现注释符了，否则编译器只把一部分看成注释，就会报错。

有的C代码中有类似// comment的注释，两个/斜线（Slash）表示从这里直到该行末尾的所有字符都属于注释，这种注释不能跨行，也不能穿插在一行代码中间。这是从C++借鉴的语法，在C99中被标准化。

C语言的发展历史大致上分为三个阶段：Old Style C、C89和C99。Ken Thompson和Dennis Ritchie最初发明C语言时有很多语法和现在最常用的写法并不一样，但为了向后兼容性（Backward Compatibility），这些语法仍然在C89和C99中保留下来了。C89是最早的C语言规范，于1989年提出，1990年首先由ANSI（美国国家标准委员会，American National Standards Institute）推出，后来被接纳为ISO国际标准（ISO/IEC 9899:1990），因而有时也称为C90，C89是目前最广泛采用的C语言标准，大多数编译器都完全支持C89。C99标准（ISO/IEC 9899:1999）是在1999年推出的，加入了许多新特性。
