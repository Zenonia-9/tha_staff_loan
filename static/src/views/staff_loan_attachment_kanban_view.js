import { registry } from "@web/core/registry";
import { kanbanView } from "@web/views/kanban/kanban_view";
import { KanbanController } from "@web/views/kanban/kanban_controller";
import { StaffLoanDocumentUploader } from "../components/staff_loan_document_uploader/staff_loan_document_uploader";

export class StaffLoanAttachmentKanbanController extends KanbanController {
    static components = {
        ...KanbanController.components,
        StaffLoanDocumentUploader,
    };
}

export const staffLoanAttachmentKanbanView = {
    ...kanbanView,
    Controller: StaffLoanAttachmentKanbanController,
    buttonTemplate: "tha_staff_loan.AttachmentKanbanView.Buttons",
};

registry.category("views").add("staff_loan_attachment_kanban", staffLoanAttachmentKanbanView);
