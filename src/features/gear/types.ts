export interface Item {
  id: string
  name: string
  slot: string
  minimumLevel: number
  effects: ItemEffect[]
}

export interface ItemEffect {
  name: string
  value: number | string
  type: string
}

export interface GearSet {
  name: string
  items: Record<string, string>
}
