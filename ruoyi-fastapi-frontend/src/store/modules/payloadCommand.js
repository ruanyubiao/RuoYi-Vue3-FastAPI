const usePayloadCommandStore = defineStore('payloadCommand', {
  state: () => ({
    filterText: '',
    currentOrderId: '',
    compValues: [],
    assembledHex: '',
    assembledLength: 0,
    assembledAllChannel: false,
    orderDrafts: {},
    expandedTreeKeys: []
  }),
  actions: {
    setFilterText(text) {
      this.filterText = text || ''
    },
    addExpandedTreeKey(key) {
      if (!key || this.expandedTreeKeys.includes(key)) return
      this.expandedTreeKeys.push(key)
    },
    removeExpandedTreeKey(key) {
      this.expandedTreeKeys = this.expandedTreeKeys.filter(item => item !== key)
    },
    setExpandedTreeKeys(keys) {
      this.expandedTreeKeys = Array.isArray(keys) ? [...keys] : []
    },
    persistCurrentDraft() {
      if (!this.currentOrderId) return
      this.orderDrafts[this.currentOrderId] = {
        compValues: Array.isArray(this.compValues) ? [...this.compValues] : [],
        assembledHex: this.assembledHex,
        assembledLength: this.assembledLength,
        assembledAllChannel: this.assembledAllChannel
      }
    },
    switchOrder(orderId, defaultValues) {
      this.persistCurrentDraft()
      this.currentOrderId = orderId || ''
      const draft = orderId ? this.orderDrafts[orderId] : null
      if (draft) {
        this.compValues = Array.isArray(draft.compValues) ? [...draft.compValues] : []
        this.assembledHex = draft.assembledHex || ''
        this.assembledLength = draft.assembledLength || 0
        this.assembledAllChannel = !!draft.assembledAllChannel
      } else {
        this.compValues = Array.isArray(defaultValues) ? [...defaultValues] : []
        this.assembledHex = ''
        this.assembledLength = 0
        this.assembledAllChannel = false
      }
    },
    setAssembled({ hex = '', length = 0, allChannel = false } = {}) {
      this.assembledHex = hex || ''
      this.assembledLength = length || 0
      this.assembledAllChannel = !!allChannel
      this.persistCurrentDraft()
    },
    clear() {
      this.filterText = ''
      this.currentOrderId = ''
      this.compValues = []
      this.assembledHex = ''
      this.assembledLength = 0
      this.assembledAllChannel = false
      this.orderDrafts = {}
      this.expandedTreeKeys = []
    }
  }
})

export default usePayloadCommandStore
