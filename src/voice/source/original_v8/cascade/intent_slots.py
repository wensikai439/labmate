"""Constrained Chinese proposals; V6 proposal rules reviewed against training wording.

Never executes instrument commands. Ambiguous/multiple/negative/quoted
commands remain unmatched; numerical frequency needs explicit unit/value.
"""
import re
from decimal import Decimal,InvalidOperation
DIGITS={c:v for c,v in zip('零一二三四五六七八九',range(10))}
DIGITS.update({'〇':0,'两':2})
SMALL={'十':10,'百':100,'千':1000}
LARGE={'万':10000,'亿':100000000}
NUMBER=r'[+\-负]?(?:\d+(?:\.\d+)?|[零〇一二两三四五六七八九十百千万亿]+(?:点[零〇一二两三四五六七八九]+)?)'
# Prefer explicit kHz/MHz suffixes; e.g. 十五千赫兹 means 15 kHz, not 5010 Hz.
FREQUENCY_NUMBER=NUMBER.replace('[零〇一二两三四五六七八九十百千万亿]+','[零〇一二两三四五六七八九十百千万亿]+?')
FREQUENCY=re.compile('('+FREQUENCY_NUMBER+r')(兆赫兹|兆赫|mhz|千赫兹|千赫|khz|赫兹|hz)',re.I)
BLOCKED=re.compile(
    r'不要|不能|禁止|无需|不必|勿|先别|请别|你别|别再|别急|别(?:打开|开启|关闭|测|读|设|调|识别|查询)|'
    r'是否|要不要|为什么|是不是|如果|他说|她说|老师(?:说|讲|解释)|例如|示例|解释|'
    r'什么意思|是什么意思|是什么原理|什么原理|有什么关系|定义|含义|刚才|这四个字|怎么写|怎么读|'
    r'我想了解|我的问题|我想问|请回答.*问题|课本|讲义|课堂笔记|课堂上|课堂中|'
    r'不(?:准|允许|需要|打开|开启|关闭|关掉|测|读|设|调|识别|查询|使能|禁用|启动|停止)|能不能|能否|可不可以|'
    r'别(?:把|将|开通|启动|使能|禁用|停止|关掉|暂停|停掉|恢复|启用|计算|显示|获取|提示|继续|进入)|'
    r'的意思|这句话|几个字|这个词|'
    r'报告.*(?:记录|介绍|写|提)|同学.*提到|我听说|我正在复习|课堂笔记|我记得')
READ=r'(?:测量(?!记录|任务|步骤|方法|方案|指令|结果)|测一下|测出|测(?=频率|峰|有效|均方根|当前|这个|信号|示波器|仪器|通道)|量(?=频率|峰|有效|当前|这个|信号)|读取|读出|读一下|读(?=频率|峰|有效|均方根|当前|这个|信号|示波器|仪器|通道)|获取|查询|查看|显示|计算|检测)'
IDENTIFY=re.compile(
    r'(?:识别|辨认|认出).*(?:仪器|设备|示波器|信号源|发生器|电源)|'
    r'(?:读取|读出|查看|显示|查询|获取|确认|检查).*(?:型号|仪器名称|设备名称)|'
    r'(?:读取|读出|查看|显示|查询|获取|确认|检查).*(?:仪器|设备|示波器|信号源|发生器|电源).*(?:型号|名称)|'
    r'(?:列出|显示|查询|查看).*(?:可控仪器|连接的仪器|连接的设备)|'
    r'确认.*(?:连接|设备)|检查.*仪器|看看.*(?:设备|仪器).*是什么|'
    r'(?:读取|查看|显示).*(?:仪器|型号)')
SET_ACTION=r'(?:设置|设(?:为|成|到|定)|设(?=频率|信号|输出|发生器)|调(?:为|到|至|成|整|节)|改(?:为|成|到)|更改|修改)'
SET=re.compile(SET_ACTION+r'.*'+NUMBER+r'(?:兆赫|千赫|赫兹|mhz|khz|hz)|'+SET_ACTION+r'.*频率|频率.*'+SET_ACTION)
NEXT=re.compile(
    r'下一步|继续实验|继续下一|下一个.*(?:实验步骤|任务)|下一项.*实验任务|'
    r'(?:后面|随后|接下来|接着|后续).*(?:实验步骤|实验操作|操作|步骤|该.*做)|'
    r'继续显示.*实验操作|后面的实验步骤')

OUTPUT_ACTION_ON=r'(?:打开|开启|使能|启用|恢复|启动|开通)'
OUTPUT_ACTION_OFF=r'(?:关闭|停止|禁用|关掉|暂停|停掉)'
OUTPUT_TARGET=r'(?:输出|信号源|信号发生器)'
OUTPUT_ON=re.compile(OUTPUT_ACTION_ON+r'.*'+OUTPUT_TARGET+r'|(?:把|将).*'+OUTPUT_TARGET+r'.*'+OUTPUT_ACTION_ON)
OUTPUT_OFF=re.compile(OUTPUT_ACTION_OFF+r'.*'+OUTPUT_TARGET+r'|(?:把|将).*'+OUTPUT_TARGET+r'.*'+OUTPUT_ACTION_OFF)

def measurement_pattern(quantity):
    # Object-first requests need an imperative marker; descriptions are not commands.
    return re.compile(READ+r'.*(?:'+quantity+r')|(?:把|将).*(?:'+quantity+r').*'+READ)

MEASURE_FREQ=measurement_pattern(r'频率')
MEASURE_VPP=measurement_pattern(r'峰峰|峰到峰|vpp')
MEASURE_RMS=measurement_pattern(r'有效值|有效电压|均方根|rms')
AMBIGUOUS_FREQUENCY=re.compile(NUMBER+r'\s*(?:到|至|或|或者|~|～|/|—|和|与|、|,|，)\s*'+NUMBER+r'|\d+\.(?:\d*\.)+\d+')


def number_value(token):
    token=token.replace('负','-')
    if re.fullmatch(r'[+\-]?\d+(?:\.\d+)?',token):
        return Decimal(token)
    sign=-1 if token.startswith('-') else 1
    token=token.lstrip('+-')
    integer,separator,fraction=token.partition('点')
    if re.search(r'[百千][一二两三四五六七八九]$',integer):
        raise ValueError('Ambiguous abbreviated Chinese number')
    total=section=current=0
    for char in integer:
        if char in DIGITS:
            current=current*10+DIGITS[char]
        elif char in SMALL:
            section+=(current or 1)*SMALL[char]
            current=0
        elif char in LARGE:
            section+=current
            if char=='亿':
                total=(total+section)*LARGE[char]
            else:
                total+=section*LARGE[char]
            section=current=0
        else:
            raise ValueError('Unsupported number')
    value=Decimal(total+section+current)
    if separator:
        if not fraction:
            raise ValueError('Missing decimal fraction')
        value+=Decimal('0.'+''.join(str(DIGITS[c]) for c in fraction))
    return sign*value


def parse_transcript(transcript):
    text=re.sub(r'[\s，。！？、,:;；：!?]','',transcript).lower()
    result=dict(intent_proposal='UNMATCHED',frequency_hz=None,confirmation_required=True,
        instrument_control_executed=False,parser='constrained_zh_rules_v6r2',parser_board_verified=False)
    if not text:
        return dict(result,reason='empty_transcript')
    if BLOCKED.search(text):
        return dict(result,reason='negative_question_or_reported_command_requires_review')
    candidates=[]
    if IDENTIFY.search(text):
        candidates.append('CMD_IDENTIFY_INSTRUMENT')
    if SET.search(text):
        candidates.append('CMD_SET_SIGNAL_FREQ')
    for pattern,intent in [(MEASURE_FREQ,'CMD_MEASURE_FREQ'),(MEASURE_VPP,'CMD_MEASURE_VPP'),
                           (MEASURE_RMS,'CMD_MEASURE_RMS'),(OUTPUT_ON,'CMD_OUTPUT_ON'),
                           (OUTPUT_OFF,'CMD_OUTPUT_OFF')]:
        if pattern.search(text):
            candidates.append(intent)
    if NEXT.search(text):
        candidates.append('CMD_NEXT')
    candidates=list(dict.fromkeys(candidates))
    if len(candidates)!=1:
        return dict(result,reason='multiple_or_unsupported_intents',candidates=candidates)
    intent=candidates[0]
    if intent=='CMD_SET_SIGNAL_FREQ':
        if AMBIGUOUS_FREQUENCY.search(transcript):
            return dict(result,reason='ambiguous_or_invalid_frequency')
        values=list(FREQUENCY.finditer(text))
        if len(values)!=1:
            return dict(result,reason='missing_or_multiple_explicit_frequency_values')
        if values[0].start()>0 and text[values[0].start()-1] in '0123456789.点零〇一二两三四五六七八九十百千万亿':
            return dict(result,reason='ambiguous_or_invalid_frequency')
        try:
            value=number_value(values[0][1])
            unit=values[0][2].lower()
            value*=1000000 if unit.startswith(('m','兆')) else 1000 if unit.startswith(('k','千')) else 1
            if value<=0 or not value.is_finite():
                raise ValueError('Frequency must be positive')
        except (ValueError,KeyError,InvalidOperation):
            return dict(result,reason='ambiguous_or_invalid_frequency')
        result['frequency_hz']=int(value) if value==value.to_integral() else float(value)
        result['frequency_requires_instrument_range_validation']=True
    return dict(result,intent_proposal=intent,reason='single_supported_command_proposal')
