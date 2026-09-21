let seeded=null

function seedTask(task){
  seeded=task||null
}

function takeSeed(id){
  const task=seeded && (!id || seeded.id===id) ? seeded : null
  seeded=null
  return task
}

module.exports={seedTask,takeSeed}
