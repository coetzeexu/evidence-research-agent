import * as Dialog from '@radix-ui/react-dialog';
import { CircleHelp, X } from 'lucide-react';

export default function ResearchHelp() {
  return (
    <Dialog.Root>
      <Dialog.Trigger asChild>
        <button
          className="icon-button research-help-trigger"
          aria-label="查看研究流程"
          title="研究流程"
        >
          <CircleHelp size={17} />
        </button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="research-help-overlay" />
        <Dialog.Content className="research-help-panel">
          <Dialog.Title>一次研究如何完成</Dialog.Title>
          <Dialog.Description>从问题到报告，进展会持续出现在会话中。</Dialog.Description>
          <ol>
            <li>
              <strong>确定研究范围</strong>
              <p>识别资产、时间和研究目标；信息不足时向你确认。</p>
            </li>
            <li>
              <strong>读取数据与核实事件</strong>
              <p>查看正在执行的步骤、工具和来源，随时展开细节。</p>
            </li>
            <li>
              <strong>查看报告，继续追问</strong>
              <p>报告就绪后切换查看，也可以在原会话里继续讨论。</p>
            </li>
          </ol>
          <Dialog.Close asChild>
            <button className="icon-button research-help-close" aria-label="关闭研究流程">
              <X size={17} />
            </button>
          </Dialog.Close>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
