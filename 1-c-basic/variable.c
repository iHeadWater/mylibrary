#include <stdio.h>

char firstletter = 'a';
int hour = 11, minute = 59;
int total_minute;

int main(void){
    printf("常量：\ncharacter: %c\ninteger: %d\nfloating point: %f\n", '}', 34, 3.14);
    printf("变量：\nCurrent time is %d:%d\n", hour, minute);
    total_minute = hour * 60 + minute;
    printf("表达式：\n%d:%d is %d minutes after 00:00\n", hour, minute, hour * 60 + minute);
    printf("%d:%d is %d minutes after 00:00\n", hour, minute, total_minute = hour * 60 + minute);
    printf("整数除法：\n%d and %d hours\n", hour, minute / 60);
    printf("%d hours and %d percent of an hour\n", hour, minute * 100 / 60);
    printf("%d and %f hours\n", hour, minute / 60.0);
}