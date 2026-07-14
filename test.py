

#  Copyright (c) 2026 xuehui_li
# 253MS c
# 222MS c
# 174MS c
# 332MS python

#  Licensed under the Custom Non-Commercial Copyleft License.
#  Commercial use is prohibited without prior written permission.
#
#  Any project, software, or derivative work that uses, modifies, links to,
#  or incorporates this software must make its complete source code publicly
#  available under the same license.
#
#  This software is provided "as is", without warranty of any kind.

#
#
#  Any project, software, or derivative work that uses, modifies, links to,
#  or incorporates this software must make its complete source code publicly
#  available under the same license.
#
#  This software is provided "as is", without warranty of any kind.

#
#
#  Any project, software, or derivative work that uses, modifies, links to,
#  or incorporates this software must make its complete source code publicly
#  available under the same license.
#
#  This software is provided "as is", without warranty of any kind.

from numbers import Number

list = "80 90 76 95 98 87 97 96 100 91 90 86 92 88 79 87 86 99 97 96 85 89 68 96 89 93 84 100 80 100 72 76 91 90"
split = list.split(" ")
nums = []
for e in split:
    number = int(e)
    nums.append(number)
print(nums)
total = 0
for num in nums:
    total += num

print(total/len(nums))