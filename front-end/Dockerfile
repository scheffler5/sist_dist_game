FROM nginx:1.27-alpine

# Remove a config padrão do nginx
RUN rm /etc/nginx/conf.d/default.conf

# Copia nossa configuração
COPY nginx.conf /etc/nginx/conf.d/app.conf

# Copia os arquivos estáticos
COPY static/ /usr/share/nginx/html/

EXPOSE 80
