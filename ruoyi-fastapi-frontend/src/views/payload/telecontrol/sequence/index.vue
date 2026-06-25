<template>
  <div class="app-container">
    <el-form :model="queryParams" ref="queryRef" :inline="true" v-show="showSearch">
      <el-form-item label="序列名称" prop="seqName">
        <el-input
          v-model="queryParams.seqName"
          placeholder="请输入序列名称"
          clearable
          style="width: 200px"
          @keyup.enter="handleQuery"
        />
      </el-form-item>
      <el-form-item label="状态" prop="status">
        <el-select v-model="queryParams.status" placeholder="序列状态" clearable style="width: 200px">
          <el-option
            v-for="dict in sys_normal_disable"
            :key="dict.value"
            :label="dict.label"
            :value="dict.value"
          />
        </el-select>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" icon="Search" @click="handleQuery">搜索</el-button>
        <el-button icon="Refresh" @click="resetQuery">重置</el-button>
      </el-form-item>
    </el-form>

    <el-row :gutter="10" class="mb8">
      <el-col :span="1.5">
        <el-button
          type="primary"
          plain
          icon="Plus"
          @click="handleAdd"
          v-hasPermi="['payload:sequence:add']"
        >新增</el-button>
      </el-col>
      <el-col :span="1.5">
        <el-button
          type="success"
          plain
          icon="Edit"
          :disabled="single"
          @click="handleUpdate"
          v-hasPermi="['payload:sequence:edit']"
        >修改</el-button>
      </el-col>
      <el-col :span="1.5">
        <el-button
          type="danger"
          plain
          icon="Delete"
          :disabled="multiple"
          @click="handleDelete"
          v-hasPermi="['payload:sequence:remove']"
        >删除</el-button>
      </el-col>
      <right-toolbar v-model:showSearch="showSearch" @queryTable="getList"></right-toolbar>
    </el-row>

    <el-table v-loading="loading" :data="sequenceList" @selection-change="handleSelectionChange">
      <el-table-column type="selection" width="55" align="center" />
      <el-table-column label="序列编号" align="center" prop="seqId" width="90" />
      <el-table-column label="序列名称" align="center" prop="seqName" :show-overflow-tooltip="true" />
      <el-table-column label="指令条数" align="center" width="100">
        <template #default="scope">
          <el-tag type="info">{{ commandCount(scope.row.commands) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" align="center" prop="status" width="90">
        <template #default="scope">
          <dict-tag :options="sys_normal_disable" :value="scope.row.status" />
        </template>
      </el-table-column>
      <el-table-column label="备注" align="center" prop="remark" :show-overflow-tooltip="true" />
      <el-table-column label="创建时间" align="center" prop="createTime" width="180">
        <template #default="scope">
          <span>{{ parseTime(scope.row.createTime) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="280" align="center" class-name="small-padding fixed-width">
        <template #default="scope">
          <el-button link type="primary" icon="Edit" @click="handleUpdate(scope.row)" v-hasPermi="['payload:sequence:edit']">修改</el-button>
          <el-button link type="primary" icon="CopyDocument" @click="handleCopy(scope.row)" v-hasPermi="['payload:sequence:add']">复制</el-button>
          <el-button link type="success" icon="VideoPlay" @click="handleRun(scope.row)" v-hasPermi="['payload:sequence:edit']">执行</el-button>
          <el-button link type="primary" icon="Delete" @click="handleDelete(scope.row)" v-hasPermi="['payload:sequence:remove']">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <pagination
      v-show="total > 0"
      :total="total"
      v-model:page="queryParams.pageNum"
      v-model:limit="queryParams.pageSize"
      @pagination="getList"
    />

    <!-- 添加或修改指令序列对话框 -->
    <el-dialog :title="title" v-model="open" width="760px" append-to-body>
      <el-form ref="sequenceRef" :model="form" :rules="rules" label-width="80px">
        <el-form-item label="序列名称" prop="seqName">
          <el-input v-model="form.seqName" placeholder="请输入序列名称" />
        </el-form-item>
        <el-form-item label="状态" prop="status">
          <el-radio-group v-model="form.status">
            <el-radio
              v-for="dict in sys_normal_disable"
              :key="dict.value"
              :value="dict.value"
            >{{ dict.label }}</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="指令内容">
          <div style="width: 100%">
            <el-button type="primary" plain icon="Plus" size="small" @click="addCommand">添加指令</el-button>
            <el-table :data="form.commandList" border style="margin-top: 8px">
              <el-table-column label="序号" type="index" width="60" align="center" />
              <el-table-column label="指令(HEX)" align="center">
                <template #default="scope">
                  <el-input v-model="scope.row.hex" placeholder="如 AA BB CC（自动大写，排除广播帧）" @input="onHexInput(scope.row)" />
                </template>
              </el-table-column>
              <el-table-column label="名称(可选)" align="center" width="180">
                <template #default="scope">
                  <el-input v-model="scope.row.name" placeholder="备注名" />
                </template>
              </el-table-column>
              <el-table-column label="间隔(ms)" align="center" width="140">
                <template #default="scope">
                  <el-input-number v-model="scope.row.interval" :min="0" :step="100" controls-position="right" style="width: 120px" />
                </template>
              </el-table-column>
              <el-table-column label="操作" align="center" width="120">
                <template #default="scope">
                  <el-button link type="primary" icon="Top" :disabled="scope.$index === 0" @click="moveCommand(scope.$index, -1)" />
                  <el-button link type="primary" icon="Bottom" :disabled="scope.$index === form.commandList.length - 1" @click="moveCommand(scope.$index, 1)" />
                  <el-button link type="danger" icon="Delete" @click="removeCommand(scope.$index)" />
                </template>
              </el-table-column>
              <template #empty>
                <span>暂无指令，请点击「添加指令」</span>
              </template>
            </el-table>
          </div>
        </el-form-item>
        <el-form-item label="备注" prop="remark">
          <el-input v-model="form.remark" type="textarea" placeholder="请输入内容" />
        </el-form-item>
      </el-form>
      <template #footer>
        <div class="dialog-footer">
          <el-button type="primary" @click="submitForm">确 定</el-button>
          <el-button @click="cancel">取 消</el-button>
        </div>
      </template>
    </el-dialog>

    <el-dialog title="执行指令序列" v-model="runOpen" width="480px" append-to-body>
      <el-form label-width="100px">
        <el-form-item label="序列名称">
          <span>{{ runForm.seqName }}</span>
        </el-form-item>
        <el-form-item label="指令条数">
          <el-tag type="info">{{ runForm.commandCount }}</el-tag>
        </el-form-item>
        <el-form-item label="目标设备">
          <el-select v-model="runForm.deviceId" filterable placeholder="请选择 CAN 通道" style="width: 100%">
            <el-option v-for="d in deviceOptions" :key="d" :label="d" :value="d" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="runOpen = false">取 消</el-button>
        <el-button type="primary" :loading="runLoading" @click="confirmRun">开始执行</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup name="Sequence">
import { listSequence, addSequence, delSequence, getSequence, updateSequence, copySequence, runSequence } from "@/api/payload/sequence";
import { listCanChannels } from "@/api/payload/device";

const ACTIVE_KEY = "payload:activeDeviceId";

const { proxy } = getCurrentInstance();
const { sys_normal_disable } = proxy.useDict("sys_normal_disable");

const DEFAULT_INTERVAL = 2000;

const sequenceList = ref([]);
const open = ref(false);
const loading = ref(true);
const showSearch = ref(true);
const ids = ref([]);
const single = ref(true);
const multiple = ref(true);
const total = ref(0);
const title = ref("");
const runOpen = ref(false);
const runLoading = ref(false);
const deviceOptions = ref([]);
const runForm = reactive({
  seqId: undefined,
  seqName: "",
  commandCount: 0,
  deviceId: localStorage.getItem(ACTIVE_KEY) || ""
});

const data = reactive({
  form: {},
  queryParams: {
    pageNum: 1,
    pageSize: 10,
    seqName: undefined,
    status: undefined
  },
  rules: {
    seqName: [{ required: true, message: "序列名称不能为空", trigger: "blur" }]
  }
});

const { queryParams, form, rules } = toRefs(data);

/** 解析 commands(JSON文本)为数组 */
function parseCommands(commands) {
  if (!commands) return [];
  if (Array.isArray(commands)) return commands;
  try {
    const arr = JSON.parse(commands);
    return Array.isArray(arr) ? arr : [];
  } catch (e) {
    return [];
  }
}

/** 列表「指令条数」列 */
function commandCount(commands) {
  return parseCommands(commands).length;
}

/** HEX 输入：自动转大写 */
function onHexInput(row) {
  if (row.hex) {
    row.hex = row.hex.toUpperCase();
  }
}

/** 查询指令序列列表 */
function getList() {
  loading.value = true;
  listSequence(queryParams.value).then(response => {
    sequenceList.value = response.rows;
    total.value = response.total;
    loading.value = false;
  });
}
/** 取消按钮 */
function cancel() {
  open.value = false;
  reset();
}
/** 表单重置 */
function reset() {
  form.value = {
    seqId: undefined,
    seqName: undefined,
    commandList: [],
    status: "0",
    remark: undefined
  };
  proxy.resetForm("sequenceRef");
}
/** 搜索按钮操作 */
function handleQuery() {
  queryParams.value.pageNum = 1;
  getList();
}
/** 重置按钮操作 */
function resetQuery() {
  proxy.resetForm("queryRef");
  handleQuery();
}
/** 多选框选中数据 */
function handleSelectionChange(selection) {
  ids.value = selection.map(item => item.seqId);
  single.value = selection.length != 1;
  multiple.value = !selection.length;
}
/** 添加一条指令行 */
function addCommand() {
  form.value.commandList.push({ name: "", hex: "", interval: DEFAULT_INTERVAL });
}
/** 删除一条指令行 */
function removeCommand(index) {
  form.value.commandList.splice(index, 1);
}
/** 上移/下移指令行 */
function moveCommand(index, delta) {
  const list = form.value.commandList;
  const target = index + delta;
  if (target < 0 || target >= list.length) return;
  const tmp = list[index];
  list[index] = list[target];
  list[target] = tmp;
}
/** 新增按钮操作 */
function handleAdd() {
  reset();
  open.value = true;
  title.value = "添加指令序列";
}
/** 修改按钮操作 */
function handleUpdate(row) {
  reset();
  const seqId = row.seqId || ids.value;
  getSequence(seqId).then(response => {
    const detail = response.data;
    form.value = {
      seqId: detail.seqId,
      seqName: detail.seqName,
      commandList: parseCommands(detail.commands),
      status: detail.status,
      remark: detail.remark
    };
    open.value = true;
    title.value = "修改指令序列";
  });
}
/** 复制按钮：调用后端 copy 接口取草稿并预填新增表单 */
function handleCopy(row) {
  reset();
  copySequence(row.seqId).then(response => {
    const draft = response.data;
    form.value = {
      seqId: undefined,
      seqName: draft.seqName || (row.seqName + "-副本"),
      commandList: parseCommands(draft.commands),
      status: draft.status || "0",
      remark: draft.remark
    };
    open.value = true;
    title.value = "添加指令序列（复制）";
  });
}

/** 加载可选 CAN 设备列表 */
function loadDeviceOptions() {
  listCanChannels().then(res => {
    const list = (res.data || []).map(item => item.deviceId).filter(Boolean);
    deviceOptions.value = list.length ? list : ["can:0:0:0"];
    if (!runForm.deviceId && deviceOptions.value.length) {
      runForm.deviceId = deviceOptions.value[0];
    }
  });
}

/** 执行按钮：选择设备后顺序下发 */
function handleRun(row) {
  runForm.seqId = row.seqId;
  runForm.seqName = row.seqName;
  runForm.commandCount = commandCount(row.commands);
  runForm.deviceId = localStorage.getItem(ACTIVE_KEY) || deviceOptions.value[0] || "";
  loadDeviceOptions();
  runOpen.value = true;
}

function confirmRun() {
  if (!runForm.deviceId) {
    proxy.$modal.msgWarning("请选择目标设备，请先在控制开关页打开 CAN 通道");
    return;
  }
  runLoading.value = true;
  runSequence(runForm.seqId, { deviceId: runForm.deviceId }).then(res => {
    const data = res.data || {};
    const ok = (data.results || []).filter(r => r.success).length;
    proxy.$modal.msgSuccess(`序列执行完成：${ok}/${data.total || 0} 条成功`);
    localStorage.setItem(ACTIVE_KEY, runForm.deviceId);
    runOpen.value = false;
  }).catch(() => {}).finally(() => {
    runLoading.value = false;
  });
}
/** 提交按钮 */
function submitForm() {
  proxy.$refs["sequenceRef"].validate(valid => {
    if (!valid) return;
    const commandList = form.value.commandList || [];
    if (commandList.some(item => !item.hex || !item.hex.trim())) {
      proxy.$modal.msgWarning("存在空的指令HEX，请填写或删除该行");
      return;
    }
    const payload = {
      seqId: form.value.seqId,
      seqName: form.value.seqName,
      status: form.value.status,
      remark: form.value.remark,
      commands: JSON.stringify(commandList)
    };
    if (payload.seqId != undefined) {
      updateSequence(payload).then(() => {
        proxy.$modal.msgSuccess("修改成功");
        open.value = false;
        getList();
      });
    } else {
      addSequence(payload).then(() => {
        proxy.$modal.msgSuccess("新增成功");
        open.value = false;
        getList();
      });
    }
  });
}
/** 删除按钮操作 */
function handleDelete(row) {
  const seqIds = row.seqId || ids.value;
  proxy.$modal.confirm('是否确认删除指令序列编号为"' + seqIds + '"的数据项？').then(function() {
    return delSequence(seqIds);
  }).then(() => {
    getList();
    proxy.$modal.msgSuccess("删除成功");
  }).catch(() => {});
}

getList();
loadDeviceOptions();
</script>
