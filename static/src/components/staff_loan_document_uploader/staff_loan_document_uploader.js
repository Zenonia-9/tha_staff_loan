/** @odoo-module **/

import { Component } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { FileUploader } from "@web/views/fields/file_handler";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

export class StaffLoanDocumentUploader extends Component {
    static template = "tha_staff_loan.DocumentFileUploader";
    static components = {
        FileUploader,
    };
    static props = {
        ...standardWidgetProps,
        record: { type: Object, optional: true },
        slots: { type: Object, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.attachmentIdsToProcess = [];
    }

    async onFileUploaded(file) {
        const attachmentValues = {
            name: file.name,
            mimetype: file.type,
            datas: file.data,
        };
        const cleanContext = Object.fromEntries(
            Object.entries(this.env.searchModel.context).filter(([key]) => !key.startsWith("default_"))
        );
        const [attachmentId] = await this.orm.create("ir.attachment", [attachmentValues], {
            context: cleanContext,
        });
        this.attachmentIdsToProcess.push(attachmentId);
    }

    async onUploadComplete() {
        let action;
        try {
            action = await this.orm.call(
                "staff.loan",
                "create_document_from_attachment",
                [this.attachmentIdsToProcess],
                { context: { ...this.env.searchModel.context } }
            );
        } finally {
            this.attachmentIdsToProcess = [];
        }
        await this.action.doAction(action);
    }
}
