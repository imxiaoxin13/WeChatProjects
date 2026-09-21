const KIND_TEXT = {
  credit: '积分到账',
  recharge: '充值到账',
  reserve: '积分冻结',
  capture: '积分消耗',
  refund: '积分退还',
  admin_adjust: '系统发放',
}

const ORDER_TEXT = {
  pending: '处理中',
  paid: '已到账',
  rejected: '已取消',
}

function formatAmount(cents) {
  const value = Number(cents || 0)
  return (value / 100).toFixed(value % 100 ? 2 : 0)
}

function decorateOrders(orders) {
  return (orders || []).map((item) => ({
    ...item,
    statusText: ORDER_TEXT[item.status] || item.status,
    priceText: `¥${formatAmount(item.amount_cents)}`,
  }))
}

function decorateLedger(ledger) {
  return (ledger || []).map((item) => ({
    ...item,
    kindText: KIND_TEXT[item.kind] || item.kind,
  }))
}

module.exports = {formatAmount, decorateOrders, decorateLedger}
