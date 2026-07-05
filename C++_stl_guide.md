# C++ STL Data Structures — Quick Reference for Coding Interviews

All examples assume:
```cpp
#include <bits/stdc++.h>  // pulls in everything below (vector, map, set, etc.)
using namespace std;
```
(On LeetCode this is usually already done for you.)

---

## 1. `vector` — Dynamic Array
**Header:** `<vector>`
Contiguous, resizable array. Random access O(1). `push_back`/`pop_back` O(1) amortized.

**Initialization**
```cpp
vector<int> v;                    // empty
vector<int> v(5);                 // size 5, all 0
vector<int> v(5, 10);             // size 5, all 10
vector<int> v = {1, 2, 3, 4};     // from list
vector<vector<int>> grid(3, vector<int>(4, 0)); // 3x4 grid of 0s
```

**Key functions**
| Function | Description |
|---|---|
| `push_back(x)` | append element |
| `pop_back()` | remove last element |
| `size()` | number of elements |
| `empty()` | true if size == 0 |
| `front()`, `back()` | first / last element |
| `v[i]`, `v.at(i)` | access element (at() bounds-checks) |
| `insert(it, x)` | insert before iterator |
| `erase(it)` | remove element at iterator |
| `clear()` | remove all elements |
| `begin()`, `end()` | iterators for range loops/algorithms |
| `sort(v.begin(), v.end())` | from `<algorithm>`, sorts in place |

**Example**
```cpp
vector<int> v = {5, 3, 1, 4, 2};
v.push_back(6);             // {5,3,1,4,2,6}
sort(v.begin(), v.end());   // {1,2,3,4,5,6}
for (int x : v) cout << x << " ";
cout << "\nsize: " << v.size();
```

---

## 2. `array` — Fixed-Size Array
**Header:** `<array>`
Compile-time fixed size, stack-allocated. Same interface style as vector, but no resizing.

```cpp
array<int, 5> a = {1, 2, 3, 4, 5};
a.size();          // 5
a.fill(0);         // set all elements to 0
sort(a.begin(), a.end());
```

---

## 3. `deque` — Double-Ended Queue
**Header:** `<deque>`
O(1) push/pop at both front and back, plus random access (slightly slower than vector).

```cpp
deque<int> dq;
dq.push_back(1);
dq.push_front(2);   // {2, 1}
dq.pop_back();
dq.pop_front();
dq.front();
dq.back();
dq.size();
```

---

## 4. `list` — Doubly Linked List
**Header:** `<list>`
O(1) insert/erase anywhere given an iterator. No random access (`v[i]` not allowed).

```cpp
list<int> l = {1, 2, 3};
l.push_back(4);     // {1,2,3,4}
l.push_front(0);    // {0,1,2,3,4}
l.pop_back();
l.pop_front();
l.sort();           // member function, sorts in place
l.reverse();
```

---

## 5. `pair` — Two Values Together
**Header:** `<utility>` (auto-included by most headers)
Bundles two values, often used for coordinates or (value, index).

```cpp
pair<int, string> p = {1, "hello"};
// or
pair<int, string> p = make_pair(1, "hello");

cout << p.first << " " << p.second;   // 1 hello

vector<pair<int,int>> v = {{3,1}, {1,2}, {2,0}};
sort(v.begin(), v.end());  // sorts by .first, then .second
```

---

## 6. `tuple` — Three or More Values Together
**Header:** `<tuple>`

```cpp
tuple<int, string, double> t = make_tuple(1, "abc", 3.14);
cout << get<0>(t) << " " << get<1>(t) << " " << get<2>(t);

int a; string b; double c;
tie(a, b, c) = t;   // unpack into variables
```

---

## 7. `string` — Dynamic Character Array
**Header:** `<string>`

```cpp
string s = "hello";
s.length();          // or s.size() -> 5
s += " world";       // "hello world"
s.substr(0, 5);      // "hello" (start, length)
s.find("wor");       // index 6, or string::npos if not found
s.push_back('!');
s.pop_back();
sort(s.begin(), s.end());     // sorts characters: "hello" -> "ehllo"
reverse(s.begin(), s.end());
```

---

## 8. `set` — Sorted Unique Elements
**Header:** `<set>`
Stored in a balanced tree, kept sorted, duplicates ignored. O(log n) operations.

```cpp
set<int> s = {5, 1, 3, 1, 2};   // stored as {1, 2, 3, 5}

s.insert(4);                    // {1,2,3,4,5}
s.erase(2);                     // {1,3,4,5}
s.count(3);                     // 1 (0 or 1 only, since unique)

if (s.find(3) != s.end()) { /* found */ }

auto it1 = s.lower_bound(3);    // iterator to first element >= 3
auto it2 = s.upper_bound(3);    // iterator to first element > 3

for (int x : s) cout << x << " "; // iterates in sorted order: 1 3 4 5
```

---

## 9. `multiset` — Sorted Elements, Duplicates Allowed
**Header:** `<set>`
Same as `set`, but duplicate values are kept.

```cpp
multiset<int> ms = {1, 1, 2, 3};
ms.insert(1);        // {1,1,1,2,3}
ms.count(1);         // 3
ms.erase(1);         // removes ALL 1's -> {2,3}

// To remove just ONE instance:
ms.erase(ms.find(1)); // removes a single occurrence
```

---

## 10. `map` — Sorted Key-Value Pairs
**Header:** `<map>`
Keys are unique and kept sorted. O(log n) operations.

```cpp
map<string, int> m;
m["apple"] = 5;            // insert or update
m.insert({"banana", 3});
m["apple"]++;              // apple -> 6

if (m.find("apple") != m.end()) { /* key exists */ }
m.count("apple");          // 0 or 1
m.erase("apple");

for (auto& [key, val] : m) cout << key << ": " << val << "\n"; // sorted by key
```

---

## 11. `multimap` — Sorted Keys, Duplicates Allowed
**Header:** `<map>`
Like `map` but a key can map to multiple values. No `operator[]`.

```cpp
multimap<string, int> mm;
mm.insert({"a", 1});
mm.insert({"a", 2});

auto range = mm.equal_range("a");
for (auto it = range.first; it != range.second; ++it)
    cout << it->second << " ";   // 1 2
```

---

## 12. `unordered_set` — Hash Set
**Header:** `<unordered_set>`
Like `set`, but no ordering guarantee, O(1) average operations.

```cpp
unordered_set<int> us;
us.insert(5);
us.count(5);         // 1 if present, 0 if not
us.erase(5);
if (us.find(5) != us.end()) { /* found */ }
```

---

## 13. `unordered_map` — Hash Map
**Header:** `<unordered_map>`
The most commonly used container for frequency counts, caching, and "have I seen this" problems. O(1) average.

```cpp
unordered_map<int, int> freq;
for (int x : nums) freq[x]++;   // count occurrences of each value

if (freq.find(target) != freq.end()) { /* key exists */ }

for (auto& [key, val] : freq)
    cout << key << ": " << val << "\n";  // order is NOT guaranteed
```

---

## 14. `stack` — LIFO
**Header:** `<stack>`
Built on `deque` by default. No iteration — only access the top.

```cpp
stack<int> st;
st.push(1);
st.push(2);
st.top();    // 2
st.pop();    // removes 2
st.empty();
st.size();
```

---

## 15. `queue` — FIFO
**Header:** `<queue>`
Built on `deque` by default.

```cpp
queue<int> q;
q.push(1);
q.push(2);
q.front();   // 1
q.back();    // 2
q.pop();     // removes 1
q.empty();
q.size();
```

---

## 16. `priority_queue` — Heap
**Header:** `<queue>`
Max-heap by default — `top()` returns the largest element.

```cpp
priority_queue<int> pq;          // max-heap
pq.push(3);
pq.push(1);
pq.push(2);
pq.top();    // 3
pq.pop();    // removes 3

// Min-heap (smallest on top):
priority_queue<int, vector<int>, greater<int>> minHeap;
minHeap.push(3);
minHeap.push(1);
minHeap.top();  // 1

// Heap of pairs (e.g., for Dijkstra's algorithm):
priority_queue<pair<int,int>, vector<pair<int,int>>, greater<pair<int,int>>> pq2;
```

---

## Quick Decision Guide

| Need | Use |
|---|---|
| Dynamic array, random access | `vector` |
| "Have I seen this value?" | `unordered_set` |
| Frequency count / key→value lookup | `unordered_map` |
| Need sorted keys/values during iteration | `set` / `map` |
| Need duplicates with sorted order | `multiset` / `multimap` |
| LIFO (parentheses, DFS, monotonic stack) | `stack` |
| FIFO (BFS) | `queue` |
| Repeatedly get min/max ("Kth largest", Dijkstra) | `priority_queue` |
| Group multiple values together | `pair` / `tuple` |
| Need O(1) push/pop from both ends | `deque` |

---

## Common `<algorithm>` Functions (work with most containers)

```cpp
sort(v.begin(), v.end());                 // ascending
sort(v.begin(), v.end(), greater<int>());  // descending
reverse(v.begin(), v.end());
max_element(v.begin(), v.end());          // returns iterator to max
min_element(v.begin(), v.end());          // returns iterator to min
accumulate(v.begin(), v.end(), 0);         // sum (from <numeric>)
binary_search(v.begin(), v.end(), x);      // requires sorted range
lower_bound(v.begin(), v.end(), x);        // first element >= x
upper_bound(v.begin(), v.end(), x);        // first element > x
```