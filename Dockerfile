FROM scratch
USER 1001
COPY ScreenShare /ScreenShare
EXPOSE 3478/tcp
EXPOSE 3478/udp
EXPOSE 5050
WORKDIR "/"
ENTRYPOINT [ "/ScreenShare" ]
CMD ["serve"]
