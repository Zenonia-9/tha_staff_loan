import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { ListController } from "@web/views/list/list_controller";
import { StaffLoanDocumentUploader } from "../components/staff_loan_document_uploader/staff_loan_document_uploader";

export class StaffLoanAttachmentListController extends ListController {
    static components = {
        ...ListController.components,
        StaffLoanDocumentUploader,
    };
}

export const staffLoanAttachmentListView = {
    ...listView,
    Controller: StaffLoanAttachmentListController,
    buttonTemplate: "tha_staff_loan.AttachmentListView.Buttons",
};

registry.category("views").add("staff_loan_attachment_list", staffLoanAttachmentListView);
