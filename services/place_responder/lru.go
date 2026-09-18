// Part of place_responder. Licensed under AGPL-3.0.
//
// A small cache of whole answers. Its key starts with the data's generation, so a reload
// makes every old entry unreachable at once and nothing has to be cleared by hand.
package main

import (
	"container/list"
	"sync"
)

type lru struct {
	mu    sync.Mutex
	size  int
	order *list.List
	items map[string]*list.Element
}

type entry struct {
	key  string
	body []byte
}

func newLRU(size int) *lru {
	return &lru{size: size, order: list.New(), items: map[string]*list.Element{}}
}

func (c *lru) get(key string) ([]byte, bool) {
	if c.size <= 0 {
		return nil, false
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	if e, ok := c.items[key]; ok {
		c.order.MoveToFront(e)
		return e.Value.(*entry).body, true
	}
	return nil, false
}

func (c *lru) put(key string, body []byte) {
	if c.size <= 0 {
		return
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	if e, ok := c.items[key]; ok {
		e.Value.(*entry).body = body
		c.order.MoveToFront(e)
		return
	}
	c.items[key] = c.order.PushFront(&entry{key, body})
	for c.order.Len() > c.size {
		last := c.order.Back()
		c.order.Remove(last)
		delete(c.items, last.Value.(*entry).key)
	}
}
